# -*- coding: utf-8 -*-
"""v1.81 — Pedidos para RETIRAR: el depósito (Guillermo) dice a qué hora quedan listos.

Joaco (20/11/2026): "Claudio tiene que avisarle por WhatsApp a Guillermo cuando un pedido es
con el método de envío retiro en tienda, y que Guillermo conteste con un estimado de qué hora
va a tenerlo listo y preparado; en base a eso le devolvés al cliente el mensaje de cuándo está
listo".

Circuito:
1. Se confirma un pedido con retiro → (cron, en horario de la planta) WhatsApp a Guillermo
   por la cuenta Cristal Mayorista con el pedido y "¿a qué hora lo tenés listo?".
2. Guillermo contesta "a las 18" / "S07220 a las 11" / "mañana 10" → se le avisa al cliente
   "tu pedido va a estar listo hoy a las 18 hs" y a Guillermo que quedó avisado.
3. Guillermo contesta "listo" / "listo S07220" (o toca el botón en el pedido) → al cliente le
   llega "ya está listo para retirar".
4. Si no contesta: un recordatorio a los 40 min (en horario) y, si sigue sin contestar, una
   actividad para él en el pedido.

Los mensajes de Guillermo por esa cuenta NUNCA van al agente de ventas (no es un cliente).
"""
import logging
import re
from datetime import timedelta

from odoo import fields

_logger = logging.getLogger(__name__)

PARAM_PARTNER = 'cristal_agent.pickup_staff_partner_id'
PARAM_USER = 'cristal_agent.pickup_staff_user_id'
PARAM_SINCE = 'cristal_agent.pickup_staff_since'
PARAM_ENABLED = 'cristal_agent.pickup_staff_enabled'
REMIND_AFTER = timedelta(minutes=40)
ESCALATE_AFTER = timedelta(minutes=100)

_RE_ORDER = re.compile(r'\b(S\d{4,6})\b', re.IGNORECASE)
_RE_READY = re.compile(r'\b(listo|lista|listos|ya\s+est[aá]|preparad[oa]|terminad[oa])\b',
                       re.IGNORECASE)
_RE_TOMORROW = re.compile(r'\bma[nñ]ana\b', re.IGNORECASE)
_RE_IN = re.compile(r'\ben\s+(\d{1,3})\s*(min|minutos|hs?|horas?)\b', re.IGNORECASE)
_RE_HALF = re.compile(r'\ben\s+(media\s+hora|una\s+hora)\b', re.IGNORECASE)
_RE_TIME = re.compile(
    r"(?:\b(?:a\s+las|las|tipo|para\s+las|a\s+eso\s+de|como\s+a\s+las|a\s+la)\s+(\d{1,2})"
    r"(?:\s*[:.]\s*(\d{2}))?)"
    r"|(?:(?<![\d\w])(\d{1,2})\s*[:.]\s*(\d{2}))"
    r"|(?:(?<![\d\w])(\d{1,2})\s*(?:hs|h|horas)\b)"
    r"|(?:^\s*(?:ma[nñ]ana\s+)?(\d{1,2})\s*$)",
    re.IGNORECASE)


# ───────────────────────────── configuración ─────────────────────────────
def _param(env, key, default=''):
    return env['ir.config_parameter'].sudo().get_param(key, default)


def enabled(env):
    return _param(env, PARAM_ENABLED, '1') not in ('0', 'False', 'false', '')


def staff_partner(env):
    pid = int(_param(env, PARAM_PARTNER, '0') or 0)
    return env['res.partner'].sudo().browse(pid).exists()


def staff_user(env):
    uid = int(_param(env, PARAM_USER, '0') or 0)
    return env['res.users'].sudo().browse(uid).exists()


def staff_digits(env):
    p = staff_partner(env)
    d = re.sub(r'\D', '', (p.mobile or p.phone or '') if p else '')
    return d[-10:] if len(d) >= 10 else ''


def is_staff_number(env, phone):
    d = staff_digits(env)
    return bool(d) and d in re.sub(r'\D', '', phone or '')


def _account(env):
    return env['whatsapp.account'].sudo().search([('name', 'ilike', 'Mayorista')], limit=1)


def in_business_hours(env):
    """L-V 8-13 y 17-20, sábado 9-13 (horario de la planta)."""
    from .helpers import now_ar
    now = now_ar(env)
    h = now.hour + now.minute / 60.0
    if now.weekday() < 5:
        return 8 <= h < 13 or 17 <= h < 20
    if now.weekday() == 5:
        return 9 <= h < 13
    return False


# ───────────────────────────── envío ─────────────────────────────
def _send(env, partner, text, account=None):
    """WhatsApp a `partner` por la cuenta Mayorista: texto libre si hay chat (send_whatsapp
    cae solo a la plantilla de novedad de pedido si la ventana está cerrada); si no hay
    chat, directo por la plantilla de novedad de pedido (el texto lleva el S0xxxx)."""
    from .tool_registry import ToolRegistry
    from .helpers import order_update_template, order_update_ref
    account = account or _account(env)
    env2 = env(context=dict(env.context, from_cristal_agent=True, wa_transactional=True,
                            allow_opt_out=True))  # Guillermo está en No contactar (no es cliente)
    # v1.81.2 — el chat se busca por NÚMERO (el de Guillermo tiene como miembro a su
    # usuario, no al contacto "Guille": por partner no aparecía y salía todo por plantilla).
    Channel = env['discuss.channel'].sudo()
    acc_dom = [('wa_account_id', '=', account.id)] if account else []
    digits = re.sub(r'\D', '', partner.mobile or partner.phone or '')[-10:]
    channel = Channel.browse()
    if len(digits) == 10:
        channel = Channel.search([('channel_type', '=', 'whatsapp'),
                                  ('whatsapp_number', 'ilike', digits)] + acc_dom,
                                 order='write_date desc', limit=1)
    if not channel:
        channel = Channel.search(
            [('channel_type', '=', 'whatsapp'), ('channel_partner_ids', 'in', partner.ids)]
            + acc_dom, order='write_date desc', limit=1)
    if channel and channel.wa_account_id and channel.whatsapp_number and len(digits) == 10:
        # Ventana abierta (nos escribió por esa cuenta en las últimas 23 h): texto libre
        # directo en el chat, sin pasar por la plantilla.
        since = fields.Datetime.now() - timedelta(hours=23)
        if env['whatsapp.message'].sudo().search_count([
                ('mobile_number', 'ilike', digits[-8:]), ('message_type', '=', 'inbound'),
                ('wa_account_id', '=', channel.wa_account_id.id), ('create_date', '>=', since)]):
            msg = channel.with_context(from_cristal_agent=True, wa_transactional=True).message_post(
                body=text, message_type='whatsapp_message', subtype_xmlid='mail.mt_comment')
            return {'ok': True, 'mail_message_id': msg.id}
    if channel and channel.wa_account_id and channel.whatsapp_number:
        tool = ToolRegistry.get('send_whatsapp')
        return tool.execute(env=env2, run=None, channel_id=channel.id, body=f"<p>{text}</p>",
                            wa_account_id=channel.wa_account_id.id,
                            mobile_number=channel.whatsapp_number) or {}
    template = order_update_template(env, account.id if account else False)
    ref = order_update_ref(text)
    tool = ToolRegistry.get('send_whatsapp_template')
    if not (template and ref and tool):
        return {'error': 'sin chat ni plantilla de novedad de pedido'}
    return tool.execute(env=env(context=dict(env2.context, wa_policy_skip_window=True)),
                        run=None, partner_id=partner.id, template_name=template.template_name,
                        variables=[ref, text], wa_account_id=template.wa_account_id.id) or {}


def _note(order, body):
    order.sudo().message_post(body=body, subtype_xmlid='mail.mt_note')


def _lines_summary(order, limit=8):
    out = []
    lines = order.order_line.filtered(
        lambda l: not l.display_type and l.product_id and not getattr(l, 'is_delivery', False)
        and l.product_uom_qty > 0)
    for l in lines[:limit]:
        out.append(f"{l.product_uom_qty:g} {l.product_id.display_name}")
    if len(lines) > limit:
        out.append(f"y {len(lines) - limit} más")
    return ', '.join(out)


# ───────────────────────────── 1. pedirle la hora ─────────────────────────────
def awaiting_orders(env):
    """Pedidos con retiro a los que se le pidió la hora a Guillermo y todavía no salió el
    aviso de 'listo' (con o sin hora)."""
    return env['sale.order'].sudo().search([
        ('state', 'in', ('sale', 'done')), ('cristal_delivery_mode', '=', 'retiro'),
        ('cristal_pickup_staff_asked_at', '!=', False), ('cristal_pickup_ready_at', '=', False)],
        order='cristal_pickup_staff_asked_at')


def ask_staff(env, order):
    staff = staff_partner(env)
    if not staff:
        return {'error': 'sin partner del depósito configurado'}
    text = (f"🛒 Pedido para RETIRAR {order.name} de {order.partner_id.name}: "
            f"{_lines_summary(order)}. ¿A qué hora lo tenés listo? Respondé con la hora "
            f"(ej: \"a las 18\"; si hay varios: \"{order.name} a las 18\"). Cuando esté "
            f"armado respondé \"listo {order.name}\".")
    res = _send(env, staff, text)
    if res.get('ok'):
        order.sudo().cristal_pickup_staff_asked_at = fields.Datetime.now()
        _note(order, "📲 Se le pidió al depósito (Guillermo) por WhatsApp la hora en que queda "
                     "listo para retirar.")
    else:
        _logger.warning("Aviso de retiro %s al depósito no salió: %s", order.name, res)
    return res


def cron_pickup_staff(env):
    """Cada pocos minutos: pide la hora de los retiros nuevos, recuerda y escala."""
    if not enabled(env) or not staff_partner(env) or not in_business_hours(env):
        return
    Order = env['sale.order'].sudo()
    since = _param(env, PARAM_SINCE, '')
    domain = [('state', 'in', ('sale', 'done')), ('cristal_delivery_mode', '=', 'retiro'),
              ('cristal_pickup_staff_asked_at', '=', False), ('cristal_pickup_ready_at', '=', False)]
    if since:
        domain.append(('date_order', '>=', since))
    user = staff_user(env)
    for order in Order.search(domain, order='date_order', limit=10):
        if user and order.create_uid == user:
            # Lo cargó Guillermo mismo: ya sabe; no se le pregunta.
            order.cristal_pickup_staff_asked_at = fields.Datetime.now()
            continue
        try:
            ask_staff(env, order)
            env.cr.commit()
        except Exception as e:  # noqa: BLE001
            env.cr.rollback()
            _logger.exception("Aviso de retiro %s al depósito falló: %s", order.name, e)
    now = fields.Datetime.now()
    staff = staff_partner(env)
    for order in awaiting_orders(env).filtered(lambda o: not o.cristal_pickup_eta):
        try:
            waited = now - order.cristal_pickup_staff_asked_at
            if not order.cristal_pickup_reminded and waited >= REMIND_AFTER:
                res = _send(env, staff, f"⏰ Recordatorio: ¿a qué hora tenés listo {order.name} "
                                        f"de {order.partner_id.name}? Respondé "
                                        f"\"{order.name} a las 18\" (o la hora que sea).")
                if res.get('ok'):
                    order.cristal_pickup_reminded = True
            elif order.cristal_pickup_reminded and not order.cristal_pickup_escalated \
                    and waited >= ESCALATE_AFTER:
                if user:
                    order.activity_schedule(
                        'mail.mail_activity_data_todo', user_id=user.id,
                        summary=f"Decir a qué hora queda listo {order.name} (retiro)",
                        note="Respondé por WhatsApp con la hora, o avisale al cliente cuando "
                             "esté con el botón 'Avisar que está listo para retirar'.")
                order.cristal_pickup_escalated = True
            env.cr.commit()
        except Exception as e:  # noqa: BLE001
            env.cr.rollback()
            _logger.exception("Recordatorio de retiro %s falló: %s", order.name, e)


# ───────────────────────────── 2. la respuesta ─────────────────────────────
def parse_eta(env, text):
    """'a las 18' → 'hoy a las 18 hs'; 'mañana 10:30' → 'mañana a las 10:30 hs';
    'en media hora' → 'hoy a las 17:45 hs'. '' si no hay hora."""
    from .helpers import now_ar
    now = now_ar(env)
    t = text or ''
    m = _RE_HALF.search(t)
    m2 = _RE_IN.search(t)
    if m or m2:
        if m:
            mins = 30 if 'media' in m.group(1).lower() else 60
        else:
            n = int(m2.group(1))
            mins = n if m2.group(2).lower().startswith('min') else n * 60
        if not 0 < mins <= 600:
            return ''
        at = now + timedelta(minutes=mins)
        # Redondeo a 15 minutos para arriba.
        extra = (15 - at.minute % 15) % 15
        at = (at + timedelta(minutes=extra)).replace(second=0, microsecond=0)
        day = 'hoy' if at.date() == now.date() else 'mañana'
        return f"{day} a las {at:%H:%M} hs"
    clean = _RE_ORDER.sub(' ', t).strip()
    for mt in _RE_TIME.finditer(clean):
        g = mt.groups()  # (h, m) | (h, m) | (h,) | (h,)
        h = int(g[0] or g[2] or g[4] or g[5])
        mnt = int((g[1] if g[0] else g[3] if g[2] else 0) or 0)
        if 7 <= h <= 21 and mnt < 60:
            hhmm = f"{h}" if not mnt else f"{h}:{mnt:02d}"
            # Una hora que ya pasó hoy es de mañana ("a las 11" contestado a las 19).
            past = (h, mnt) <= (now.hour, now.minute)
            day = 'mañana' if (_RE_TOMORROW.search(t) or past) else 'hoy'
            return f"{day} a las {hhmm} hs"
    return ''


def _pick_order(env, text, want):
    """El pedido al que se refiere Guillermo. want = 'eta' | 'ready'."""
    pending = awaiting_orders(env)
    m = _RE_ORDER.search(text or '')
    if m:
        found = pending.filtered(lambda o: o.name.upper() == m.group(1).upper())
        return found[:1], pending
    pool = pending.filtered(lambda o: not o.cristal_pickup_eta) if want == 'eta' else pending
    if len(pool) == 1:
        return pool, pending
    if want == 'ready' and len(pending.filtered('cristal_pickup_eta')) == 1:
        return pending.filtered('cristal_pickup_eta'), pending
    return env['sale.order'], pending


def _staff_news(env, staff, order, text):
    """El depósito avisa algo del pedido (falta un producto, un cambio): queda en el pedido y
    Claudio se lo cuenta al cliente con la alternativa, sin escalar a Joaco."""
    from .claude_client import dispatch_agent_for_activity
    customer = order.partner_id
    _note(order, f"📦 El depósito (Guillermo) avisa: «{text}»")
    bot_user = env.ref('base.user_root', raise_if_not_found=False) or env.user
    activity = order.sudo().activity_schedule(
        'mail.mail_activity_data_todo', user_id=bot_user.id,
        summary=f"Novedad del depósito sobre {order.name}",
        note=(f"El depósito (Guillermo) avisa sobre el pedido {order.name}: «{text}». "
              f"Avisale a {customer.name} por WhatsApp (tratalo de vos, corto), ofrecé la "
              f"alternativa que propone el depósito y, si acepta, actualizá el pedido. No "
              f"escales a Joaco. Después cerrá esta actividad con mark_activity_done."))
    lead = env['crm.lead'].sudo().search([('partner_id', '=', customer.id)],
                                         order='id desc', limit=1)
    env.cr.commit()
    try:
        dispatch_agent_for_activity(env, customer, lead, activity)
    except Exception as e:  # noqa: BLE001
        _logger.exception("Novedad del depósito %s: Claudio no pudo avisar: %s", order.name, e)
        _send(env, staff, f"Anotado en {order.name}, pero no pude avisarle a {customer.name}: "
                          f"avisale por teléfono, por favor.")
        return 'novedad falló'
    ask = "" if order.cristal_pickup_eta else (
        f" Mientras, ¿a qué hora tenés listo el resto? (ej: \"{order.name} a las 18\")")
    _send(env, staff, f"👍 Anotado en {order.name}: ya se lo aviso a {customer.name}.{ask}")
    return 'novedad'


def handle_staff_reply(env, text):
    """Procesa un mensaje de Guillermo. Devuelve un texto con lo que se hizo (para log)."""
    from ..models.pos_mayorista import PICKUP_ADDRESS
    staff = staff_partner(env)
    text = (text or '').strip()
    if not text or not staff:
        return 'vacío'
    eta = parse_eta(env, text)
    ready = bool(_RE_READY.search(text)) and not eta
    order, pending = _pick_order(env, text, 'ready' if ready else 'eta')
    if not order:
        if not pending:
            _send(env, staff, "No tengo pedidos para retirar esperando hora. Si es por otro "
                              "tema, escribile a Joaco.")
            return 'sin pendientes'
        names = ', '.join(f"{o.name} ({o.partner_id.name})" for o in pending[:6])
        _send(env, staff, f"Tengo varios pedidos para retirar: {names}. Respondé con el número "
                          f"adelante, ej: \"{pending[0].name} a las 18\" o \"listo {pending[0].name}\".")
        return 'pidió cuál'
    customer = order.partner_id
    if ready:
        try:
            order.with_context(from_cristal_agent=True).action_cristal_pickup_ready()
        except Exception as e:  # noqa: BLE001
            _send(env, staff, f"No le pude avisar a {customer.name} que {order.name} está listo "
                              f"({str(e)[:120]}). Avisale por teléfono, por favor.")
            return 'listo falló'
        _send(env, staff, f"✅ Le avisé a {customer.name} que {order.name} ya está listo para "
                          f"retirar.")
        return 'listo'
    if not eta:
        if len(_RE_ORDER.sub(' ', text).split()) <= 3:
            # "ok", "dale", "👍": no hay nada que hacer ni que contestar.
            return 'sin acción'
        # v1.81.2 — caso Tefi S07488 (24/11): "Jabón para manos frutilla no tenemos.
        # Podemos fabricar jabón para manos blanco". Es una NOVEDAD del pedido: Claudio se la
        # cuenta al cliente y le ofrece la alternativa (antes se contestaba "No te entendí").
        return _staff_news(env, staff, order, text)
    res = _send(env, customer, f"Tu pedido {order.name} va a estar listo {eta} para retirar en "
                               f"{PICKUP_ADDRESS}. Te aviso cuando esté.")
    if not res.get('ok'):
        _send(env, staff, f"No le pude avisar a {customer.name} la hora de {order.name}: "
                          f"avisale por teléfono, por favor.")
        return 'eta falló'
    order.sudo().write({'cristal_pickup_eta': eta})
    _note(order, f"🕒 El depósito dijo que queda listo {eta}. Se le avisó al cliente por WhatsApp.")
    _send(env, staff, f"👍 Le avisé a {customer.name}: {order.name} listo {eta}. Cuando esté "
                      f"armado respondé \"listo {order.name}\" (o tocá el botón en el pedido).")
    return 'eta'
