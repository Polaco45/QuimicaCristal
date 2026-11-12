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


def _send_to_owner(env, config, text):
    channel = _owner_channel(env, config)
    if not channel or not channel.wa_account_id or not channel.whatsapp_number:
        return {"error": "Joaco no tiene chat de WhatsApp en la cuenta"}
    from .tool_registry import ToolRegistry
    tool = ToolRegistry.get('send_whatsapp')
    if not tool:
        return {"error": "send_whatsapp no disponible"}
    env2 = env(context=dict(env.context, from_cristal_agent=True, wa_transactional=True))
    return tool.execute(env=env2, run=None, channel_id=channel.id, body=text,
                        wa_account_id=channel.wa_account_id.id,
                        mobile_number=channel.whatsapp_number) or {}


def request_owner_confirmation(env, order, reason=''):
    """Le pide a Joaco por WhatsApp que confirme `order`. Una vez cada 24 h por pedido."""
    order = order.sudo()
    if order.state not in ('draft', 'sent'):
        return {"error": f"{order.name} ya no está para confirmar ({order.state})"}
    config = env['cristal.agent.config'].sudo().get_active()
    if not config or not config.owner_whatsapp_partner_id:
        return {"error": "sin WhatsApp de Joaco configurado"}
    last = order.cristal_owner_confirm_at
    if last and last > fields.Datetime.now() - timedelta(hours=24):
        return {"ok": True, "already_requested": True}
    partner = order.partner_id
    total = f"${order.amount_untaxed:,.0f}".replace(',', '.')
    if order.route_departure_id and order.route_departure_id.date:
        from .helpers import fmt_day
        entrega = f"camión del {fmt_day(order.route_departure_id.date)}"
    elif order.cristal_delivery_mode == 'retiro':
        entrega = "retira en la planta"
    else:
        entrega = f"envío a {partner.city or 'sin localidad'}"
    reason = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', reason or '')).strip()[:160]
    text = (f"Pedido para confirmar {order.name} de {partner.name}: {total} sin IVA, "
            f"{entrega}." + (f" Motivo: {reason}." if reason else "") +
            f" Respondé OK {order.name} para confirmarlo o NO {order.name} si no.")
    res = _send_to_owner(env, config, text)
    if res.get('ok'):
        order.cristal_owner_confirm_at = fields.Datetime.now()
        order.message_post(body=f"📲 Se le pidió a Joaco por WhatsApp que confirme el pedido.",
                           subtype_xmlid='mail.mt_note')
    return res


def handle_owner_reply(env, text):
    """Procesa la respuesta de Joaco. Devuelve True si era una respuesta de confirmación."""
    text = (text or '').strip()
    yes, no = _RE_YES.match(text), _RE_NO.match(text)
    m = _RE_ORDER.search(text)
    if not (yes or no):
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
