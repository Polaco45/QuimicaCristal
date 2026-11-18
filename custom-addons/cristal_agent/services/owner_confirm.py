# -*- coding: utf-8 -*-
"""
v1.67 — Confirmación de pedidos por el WhatsApp de Joaco.

Joaco (12/11/2026): "confirma todos los pedidos hasta 200k… y que me escriba por WhatsApp
para confirmar pedidos, no por el interno". Lo que confirm_order no puede confirmar solo
(más de $200.000, facturas vencidas, fuera de zona, etc.) le llega a Joaco por WhatsApp
(cuenta Cristal Mayorista) con un texto corto. Él responde:
  - "OK S07123" / "sí" / "dale"  → se confirma el pedido a su nombre (y el cliente recibe
    el aviso de pedido confirmado, v1.62).
  - "NO S07123"                    → queda sin confirmar y se anota en el pedido.
Si responde solo "ok" y hay un único pedido pedido en las últimas 48 h, se toma ese.
"""
import logging
import re
from datetime import timedelta

from odoo import fields

_logger = logging.getLogger(__name__)

_RE_ORDER = re.compile(r'\b(S\d{4,6})\b', re.IGNORECASE)
_RE_YES = re.compile(r'^\s*(ok|okey|okay|s[ií]|dale|confirm\w*|listo|va|de una)\b', re.IGNORECASE)
_RE_NO = re.compile(r'^\s*(no|cancel\w*|esper\w*|todav[ií]a no)\b', re.IGNORECASE)


def _owner_channel(env, config):
    partner = config.owner_whatsapp_partner_id
    if not partner:
        return env['discuss.channel']
    Channel = env['discuss.channel'].sudo()
    domain = [('channel_type', '=', 'whatsapp'), ('channel_partner_ids', 'in', partner.ids)]
    # Preferimos la cuenta mayorista (la misma con la que habla Claudio con los clientes).
    acc = env['whatsapp.account'].sudo().search([('name', 'ilike', 'Mayorista')], limit=1)
    ch = Channel.search(domain + ([('wa_account_id', '=', acc.id)] if acc else []),
                        order='write_date desc', limit=1)
    return ch or Channel.search(domain, order='write_date desc', limit=1)


def _send_to_owner(env, config, text, attachment_ids=None):
    channel = _owner_channel(env, config)
    if not channel or not channel.wa_account_id or not channel.whatsapp_number:
        return {"error": "Joaco no tiene chat de WhatsApp en la cuenta"}
    from .tool_registry import ToolRegistry
    tool = ToolRegistry.get('send_whatsapp')
    if not tool:
        return {"error": "send_whatsapp no disponible"}
    env2 = env(context=dict(env.context, from_cristal_agent=True, wa_transactional=True,
                            cristal_system_attachments=True))
    return tool.execute(env=env2, run=None, channel_id=channel.id, body=text,
                        wa_account_id=channel.wa_account_id.id,
                        mobile_number=channel.whatsapp_number,
                        attachment_ids=attachment_ids or None) or {}


# v1.74 — Joaco (17/11/2026): "¿en base a qué criterio me sigue mandando pedidos para
# confirmar, si era autónomo?". De 7 pedidos pedidos en dos días, 3 llegaron sin motivo.
# Ahora el motivo lo calcula el sistema (la misma lista de control de confirm_order), el
# pedido viaja con la orden en PDF, y lo que pasa los controles o solo necesita un dato
# del cliente no se le pide a Joaco.
_CLIENT_FIXABLE = ('falta la dirección de entrega', 'falta confirmar los bidones')


def confirm_blockers(env, order):
    """Motivos EXACTOS por los que `order` no se confirma solo (lista de control de
    confirm_order). Lista vacía = pasa todos los controles."""
    from .tool_registry import ToolRegistry
    tool = ToolRegistry.get('confirm_order')
    config = env['cristal.agent.config'].sudo().get_active()
    if not tool or not config:
        return ["no se pudo revisar la lista de control"]
    try:
        return list(tool._problems(env, config, order.partner_id, order))
    except Exception as e:  # noqa: BLE001 — sin lista de control decide Joaco
        _logger.exception("No pude revisar la lista de control de %s", order.name)
        return [f"no se pudo revisar la lista de control ({str(e)[:80]})"]


def only_client_fixable(problems):
    """True si lo único que falta lo resuelve el cliente (dirección, bidones)."""
    return bool(problems) and all(
        any(p.startswith(k) for k in _CLIENT_FIXABLE) for p in problems)


def _order_pdf(env, order):
    """ID del PDF de la orden (ir.attachment) o False si no se pudo generar."""
    from .tool_registry import ToolRegistry
    tool = ToolRegistry.get('generate_quote_pdf')
    try:
        res = tool.execute(env=env, run=None, sale_order_id=order.id) if tool else {}
        return (res or {}).get('attachment_id') or False
    except Exception:  # noqa: BLE001 — el pedido se manda igual, con el link
        _logger.exception("No pude generar el PDF de %s para Joaco", order.name)
        return False


def _order_pdf_link(order):
    """Link al PDF de la orden (sirve aunque el mensaje salga por plantilla, que no
    lleva adjuntos)."""
    try:
        order._portal_ensure_token()
        return order.get_base_url() + order.get_portal_url(report_type='pdf')
    except Exception:  # noqa: BLE001
        return ''


def request_owner_confirmation(env, order, reason='', force=False):
    """Le pide a Joaco por WhatsApp que confirme `order`. Una vez cada 24 h por pedido.
    Si el pedido pasa todos los controles, o solo le falta un dato del cliente, NO se le
    pide (salvo `force`, que usa la alarma de 24 h)."""
    order = order.sudo()
    if order.state not in ('draft', 'sent'):
        return {"error": f"{order.name} ya no está para confirmar ({order.state})"}
    config = env['cristal.agent.config'].sudo().get_active()
    if not config or not config.owner_whatsapp_partner_id:
        return {"error": "sin WhatsApp de Joaco configurado"}
    last = order.cristal_owner_confirm_at
    if last and last > fields.Datetime.now() - timedelta(hours=24):
        return {"ok": True, "already_requested": True}
    problems = confirm_blockers(env, order)
    if not force:
        if not problems:
            return {"ok": False, "passes_checklist": True}
        if only_client_fixable(problems):
            return {"ok": False, "client_fixable": True, "problems": problems}
    partner = order.partner_id
    total = f"${order.amount_untaxed:,.0f}".replace(',', '.')
    if order.route_departure_id and order.route_departure_id.date:
        from .helpers import fmt_day
        entrega = f"camión del {fmt_day(order.route_departure_id.date)}"
    elif order.cristal_delivery_mode == 'retiro':
        entrega = "retira en la planta"
    else:
        entrega = f"envío a {partner.city or 'sin localidad'}"
    reason = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', reason or '')).strip().rstrip('.')[:120]
    # El mensaje puede salir por plantilla (tope de 900 caracteres con el link incluido).
    why = '; '.join(problems)
    if len(why) > 300:
        why = why[:297].rsplit(' ', 1)[0] + '…'
    link = _order_pdf_link(order)
    text = (f"Pedido para confirmar {order.name} de {partner.name}: {total} sin IVA, "
            f"{entrega}. "
            + (f"No lo confirmé solo porque: {why}. " if why else
               "Pasa todos los controles, pero nadie lo confirmó. ")
            + (f"Nota: {reason}. " if reason else "")
            + (f"Orden: {link} " if link else "")
            + f"Respondé OK {order.name} para confirmarlo o NO {order.name} si no.")
    pdf = _order_pdf(env, order)
    res = _send_to_owner(env, config, text, attachment_ids=[pdf] if pdf else None)
    if res.get('ok'):
        order.cristal_owner_confirm_at = fields.Datetime.now()
        order.message_post(
            body=("📲 Se le pidió a Joaco por WhatsApp que confirme el pedido. Motivo: "
                  + (why or 'pasa los controles y seguía sin confirmar') + "."),
            subtype_xmlid='mail.mt_note')
    return res


def pending_requests(env, at=None, open_only=True):
    """Pedidos sin confirmar que se le pidieron a Joaco en las 48 h previas a `at`,
    del pedido más reciente al más viejo."""
    at = at or fields.Datetime.now()
    states = [('state', 'in', ('draft', 'sent'))] if open_only else []
    return env['sale.order'].sudo().search(
        states + [
         ('cristal_owner_confirm_at', '>=', at - timedelta(hours=48)),
         ('cristal_owner_confirm_at', '<=', at + timedelta(seconds=5))],
        order='cristal_owner_confirm_at desc, id desc')


def pending_order_for_reply(env, text, at=None, open_only=True):
    """v1.72.3 — Pedido al que se refiere una respuesta LIBRE de Joaco (ni OK ni NO).
    Joaco (16/11/2026) respondió con indicaciones ("modifiqué la cotización, mandásela
    corregida") y nadie lo atendió. Es el pedido que nombra o, si no nombra ninguno, el
    último que se le pidió confirmar antes de su mensaje (`at`). Si se le pidieron varios
    casi juntos (menos de 2 minutos entre los dos últimos) no se adivina: vacío."""
    SO = env['sale.order'].sudo()
    m = _RE_ORDER.search(text or '')
    if m:
        return SO.search([('name', '=ilike', m.group(1))], limit=1)
    orders = pending_requests(env, at, open_only=open_only)
    if len(orders) <= 1:
        return orders
    gap = orders[0].cristal_owner_confirm_at - orders[1].cristal_owner_confirm_at
    return orders[0] if gap > timedelta(minutes=2) else SO


def ask_owner_which_order(env, at=None):
    """Joaco dio una indicación y hay varios pedidos esperando: se le pregunta cuál."""
    orders = pending_requests(env, at)
    if not orders:
        return False
    config = env['cristal.agent.config'].sudo().get_active()
    names = ', '.join(f"{o.name} ({o.partner_id.name})" for o in orders[:5])
    _send_to_owner(env, config, f"¿De qué pedido me hablás? Tengo esperando: {names}. "
                                f"Mandame el mensaje de nuevo con el número adelante.")
    return True


def handle_owner_reply(env, text):
    """Procesa la respuesta de Joaco. Devuelve True si era una respuesta de confirmación."""
    text = (text or '').strip()
    yes, no = _RE_YES.match(text), _RE_NO.match(text)
    m = _RE_ORDER.search(text)
    # v1.72.3 — un mensaje largo es una indicación, no un OK/NO (aunque empiece con "no, …").
    if not (yes or no) or len(text.split()) > 6:
        return False
    config = env['cristal.agent.config'].sudo().get_active()
    SO = env['sale.order'].sudo()
    if m:
        order = SO.search([('name', '=ilike', m.group(1))], limit=1)
    else:
        order = SO.search([('state', 'in', ('draft', 'sent')),
                           ('cristal_owner_confirm_at', '>=',
                            fields.Datetime.now() - timedelta(hours=48))])
        if len(order) != 1:
            if order:
                _send_to_owner(env, config, "Hay varios pedidos esperando: respondé con el "
                                            "número, por ejemplo OK " + order[0].name + ".")
            return bool(order)
    if not order:
        _send_to_owner(env, config, f"No encontré el pedido {m.group(1) if m else ''}.")
        return True
    if order.state not in ('draft', 'sent'):
        _send_to_owner(env, config, f"{order.name} ya estaba {dict(order._fields['state'].selection).get(order.state, order.state).lower()}.")
        return True
    if no:
        order.message_post(body="Joaco respondió por WhatsApp que NO se confirma.",
                           subtype_xmlid='mail.mt_note')
        _send_to_owner(env, config, f"Listo, {order.name} queda sin confirmar.")
        return True
    user = config.owner_partner_id.user_ids[:1] or env.ref('base.user_root')
    try:
        order.with_user(user).with_context(cristal_owner_whatsapp=True).action_confirm()
    except Exception as e:  # noqa: BLE001
        _logger.warning("Joaco confirmó %s por WhatsApp pero falló: %s", order.name, e)
        _send_to_owner(env, config, f"No pude confirmar {order.name}: {str(e)[:120]}. "
                                    f"Confirmalo desde Odoo.")
        return True
    order.message_post(body="✅ Confirmado por Joaco desde WhatsApp.", subtype_xmlid='mail.mt_note')
    _send_to_owner(env, config, f"✅ Confirmé {order.name} de {order.partner_id.name}. "
                                f"Le aviso al cliente.")
    return True


# v1.76 — Joaco (18/11/2026): "no quiero intervenir más yo en pedidos, que sea autónomo".
# Ya no se le pide a Joaco que confirme: lo que la lista de control no deja pasar se
# resuelve con el cliente. Se puede volver al esquema anterior con el parámetro
# cristal_agent.owner_confirm_whatsapp = 1.
def owner_confirm_enabled(env):
    return str(env['ir.config_parameter'].sudo().get_param(
        'cristal_agent.owner_confirm_whatsapp') or '0').strip() == '1'


def autonomous_guidance(problems):
    """Qué tiene que hacer Claudio con cada motivo, sin pasar por Joaco."""
    tips = []
    for p in problems or []:
        if p.startswith('falta la dirección'):
            tips.append("pedile la dirección exacta (o si retira en el local)")
        elif p.startswith('falta confirmar los bidones'):
            tips.append("preguntale cuántos bidones vacíos de 20 L con tapa tiene y cargalo "
                        "con create_sale_order (bidones_nuevos)")
        elif p.startswith('envío fuera de'):
            tips.append("su localidad no tiene reparto: ofrecé retiro en el local o "
                        "comisionista y recotizá con delivery_mode='retiro'")
        elif p.startswith('no hay stock suficiente de'):
            tips.append(p + ": decíselo y preguntale si lo confirmás con lo que hay "
                            "(ajustá la cantidad) o si espera la reposición")
        elif p.startswith('tiene facturas vencidas'):
            tips.append("tiene saldo vencido: decile con respeto que para confirmar primero "
                        "hay que regularizarlo y pasale el saldo; no confirmes hasta entonces")
        elif p.startswith('la salida del camión'):
            tips.append("esa salida del camión ya pasó o se postergó: recotizá para la "
                        "próxima salida (get_route_info) o con retiro")
        elif p.startswith('descuento mayor'):
            tips.append("la cotización tiene un descuento mayor al permitido: recotizá con "
                        "los descuentos normales")
        else:
            tips.append(p)
    return "; ".join(tips)
