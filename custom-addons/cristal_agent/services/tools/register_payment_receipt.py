# -*- coding: utf-8 -*-
"""
Tool: register_payment_receipt (v1.66, conversión punto 10)

El cliente manda el comprobante de una transferencia (foto o PDF). Claudio NO registra el
pago (eso se concilia contra el banco): guarda el comprobante en el pedido (o en el
cliente), deja una actividad para quien verifica los cobros (config.payment_receipt_user_id)
y avisa en el canal interno. Al cliente le dice que lo recibió y que se verifica.
"""
import base64
import logging
from datetime import datetime, timedelta

from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

MEDIA_MIMES = ('image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'application/pdf')


@ToolRegistry.register
class RegisterPaymentReceipt(AgentTool):
    name = "register_payment_receipt"
    description = (
        "Cuando el cliente manda el COMPROBANTE de una transferencia (foto o PDF), pasá el "
        "monto que figura y, si es de un pedido, el order_id. Guarda el comprobante y lo "
        "pasa a quien verifica los cobros. Después decile al cliente: 'Recibimos el "
        "comprobante, lo verificamos y le confirmamos.' NUNCA digas que el pago está "
        "acreditado ni que la deuda quedó saldada."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del cliente."},
            "amount": {"type": "number", "description": "Monto que figura en el comprobante."},
            "order_id": {"type": "integer",
                         "description": "Pedido o cotización que paga (opcional)."},
            "note": {"type": "string",
                     "description": "Fecha, banco u otro dato útil que diga el comprobante."},
        },
        "required": ["partner_id", "amount"],
    }

    def _last_inbound_media(self, env, partner):
        """Último archivo (foto/PDF) que mandó el cliente por WhatsApp en las últimas 48 h."""
        channel = env['discuss.channel'].sudo().search([
            ('channel_type', '=', 'whatsapp'), ('channel_partner_ids', 'in', partner.ids)],
            order='write_date desc', limit=1)
        if not channel:
            return env['ir.attachment']
        msgs = env['mail.message'].sudo().search([
            ('model', '=', 'discuss.channel'), ('res_id', '=', channel.id),
            ('author_id', '=', partner.id), ('attachment_ids', '!=', False),
            ('date', '>=', datetime.now() - timedelta(hours=48))],
            order='id desc', limit=5)
        for m in msgs:
            for a in m.attachment_ids:
                if (a.mimetype or '') in MEDIA_MIMES:
                    return a
        return env['ir.attachment']

    def _execute(self, env, run=None, partner_id=None, amount=None, order_id=None,
                 note=None, **kwargs):
        partner = env['res.partner'].sudo().browse(int(partner_id or 0))
        if not partner.exists():
            return {"error": "partner_id no existe"}
        try:
            amount = float(amount or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        order = env['sale.order'].sudo().browse(int(order_id or 0)) if order_id else \
            env['sale.order']
        if order and (not order.exists()
                      or order.partner_id.commercial_partner_id != partner.commercial_partner_id):
            order = env['sale.order']
        target = order or partner
        src = self._last_inbound_media(env, partner)
        copy = env['ir.attachment']
        if src:
            copy = env['ir.attachment'].sudo().create({
                'name': f"Comprobante transferencia - {src.name or 'archivo'}",
                'type': 'binary', 'datas': src.datas, 'mimetype': src.mimetype,
                'res_model': target._name, 'res_id': target.id})
        monto = f"${amount:,.0f}".replace(',', '.')
        ref = f" — {order.name}" if order else ""
        body = (f"🧾 Comprobante de transferencia por {monto}{ref} recibido por WhatsApp."
                f"{(' ' + note) if note else ''} Falta verificarlo en el banco.")
        target.with_context(from_cristal_agent=True).message_post(
            body=body, attachment_ids=copy.ids, subtype_xmlid='mail.mt_note')
        config = env['cristal.agent.config'].sudo().get_active()
        user = config.payment_receipt_user_id if config else False
        if user:
            target.activity_schedule(
                'mail.mail_activity_data_todo', user_id=user.id,
                summary=f"Verificar transferencia {monto}: {partner.name}{ref}",
                note=(f"El cliente mandó el comprobante por WhatsApp (adjunto en el chatter). "
                      f"Verificalo en el banco y registrá el cobro. {note or ''}"))
        try:
            if config and config.internal_channel_id:
                config.internal_channel_id.sudo().with_context(
                    from_cristal_agent=True).message_post(
                    body=(f"🧾 {partner.name} mandó un comprobante de transferencia por "
                          f"{monto}{ref}." + (f" Lo verifica {user.name}." if user else "")),
                    message_type='comment', subtype_xmlid='mail.mt_comment')
        except Exception as e:  # noqa: BLE001
            _logger.warning("register_payment_receipt: no pude avisar en el canal: %s", e)
        return {"ok": True, "receipt_saved": bool(copy), "verifier": user.name if user else None,
                "message_for_bot": (
                    "Comprobante guardado y pasado para verificar. Decile al cliente: "
                    "'Recibimos el comprobante, lo verificamos y le confirmamos.' No digas "
                    "que el pago está acreditado."
                    + ("" if copy else " (No encontré la foto o el PDF en el chat: si no lo "
                       "mandó todavía, pedile que lo mande.)"))}
