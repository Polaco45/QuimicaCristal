# -*- coding: utf-8 -*-
"""
Tool: derive_delivery_issue (v1.65, conversión punto 11)

Las consultas de entrega ("¿cuándo me llega?", "no me llegó", "faltó un bidón") y los
reclamos del pedido eran el 12 % de los pases a Joaco. Ahora Claudio los deriva directo al
responsable de entregas (config.delivery_issue_user_id, Guillermo) con el pedido ya
identificado: le crea una actividad en el pedido (o en el cliente) y deja constancia en el
canal interno. Joaco no tiene que reenviar nada.
"""
import logging

from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

KINDS = {
    'entrega': 'Consulta de entrega',
    'faltante': 'Faltante o error en el pedido',
    'reclamo': 'Reclamo por producto o entrega',
}


@ToolRegistry.register
class DeriveDeliveryIssue(AgentTool):
    name = "derive_delivery_issue"
    description = (
        "Derivá al responsable de entregas una consulta de entrega de un pedido YA "
        "CONFIRMADO (cuándo llega, no llegó, horario) o un reclamo/faltante del pedido. "
        "Buscá antes el pedido con search_orders y pasá order_id. No lo uses para cotizar "
        "ni para dudas de precio. Después decile al cliente que ya lo pasaste a la persona "
        "de entregas, que lo está viendo y que le escriben por este medio; no prometas día "
        "ni hora. Un reclamo grave (producto que hizo daño, maltrato, amenaza de no "
        "comprar más) además va a Joaco con escalate_to_joaco."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del cliente."},
            "order_id": {"type": "integer",
                         "description": "ID del pedido confirmado (search_orders). Opcional "
                                        "si no lo encontrás."},
            "kind": {"type": "string", "enum": list(KINDS),
                     "description": "entrega | faltante | reclamo"},
            "detail": {"type": "string",
                       "description": "Qué dijo el cliente, en una o dos líneas, con los "
                                      "datos útiles (qué falta, desde cuándo espera, etc.)."},
        },
        "required": ["partner_id", "kind", "detail"],
    }

    def _execute(self, env, run=None, partner_id=None, order_id=None, kind=None,
                 detail=None, **kwargs):
        partner = env['res.partner'].sudo().browse(int(partner_id or 0))
        if not partner.exists():
            return {"error": "partner_id no existe"}
        if kind not in KINDS:
            return {"error": "kind tiene que ser entrega, faltante o reclamo"}
        config = env['cristal.agent.config'].sudo().get_active()
        user = config.delivery_issue_user_id if config else False
        if not user:
            return {"error": "NO_RESPONSABLE", "not_sent": True,
                    "message": "No hay responsable de entregas configurado: usá "
                               "escalate_to_joaco con el mismo detalle."}
        order = env['sale.order'].sudo().browse(int(order_id or 0)) if order_id else \
            env['sale.order']
        if order and (not order.exists()
                      or order.partner_id.commercial_partner_id != partner.commercial_partner_id):
            order = env['sale.order']
        target = order or partner
        title = KINDS[kind]
        ref = f" — {order.name}" if order else ""
        target.activity_schedule(
            'mail.mail_activity_data_todo', user_id=user.id,
            summary=f"{title}: {partner.name}{ref}",
            note=(f"{detail}\n\nLo derivó Claudio desde WhatsApp. Contestale al cliente por "
                  f"su chat."))
        try:
            if config.internal_channel_id:
                config.internal_channel_id.sudo().with_context(
                    from_cristal_agent=True).message_post(
                    body=(f"📦 {title} de {partner.name}{ref}: se la pasé a {user.name}. "
                          f"Detalle: {detail}"),
                    message_type='comment', subtype_xmlid='mail.mt_comment')
        except Exception as e:  # noqa: BLE001
            _logger.warning("derive_delivery_issue: no pude avisar en el canal: %s", e)
        _logger.info("📦 %s de %s derivado a %s", title, partner.name, user.name)
        return {"ok": True, "assigned_to": user.name,
                "message_for_bot": (
                    f"Listo, lo derivé a {user.name}, que se encarga de las entregas. "
                    f"Decile al cliente que ya lo pasaste a la persona de entregas y que le "
                    f"escriben por acá; no prometas día ni hora.")}
