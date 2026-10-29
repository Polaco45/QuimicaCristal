# -*- coding: utf-8 -*-
"""
Tool: confirm_cf_order (v1.48)

Confirma SOLA la cotización de un consumidor final (Joaco, 28/10/2026: "que confirme solo
y solo pago transferencia y efectivo primero"). Solo si se cumple todo:
- lista L.C 1 (precio público) y cliente consumidor final;
- envío en Río Cuarto / Las Higueras con dirección cargada, o retiro en el local;
- stock para cada producto;
- pago en efectivo o por transferencia.
Si algo no se cumple, no confirma y le dice a Claudio que siga el camino normal (escalar).
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

PAYMENTS = {'efectivo': 'Efectivo (contra entrega o al retirar)',
            'transferencia': 'Transferencia'}
CF_PRICELIST = 'L.C 1'


@ToolRegistry.register
class ConfirmCfOrder(AgentTool):
    name = "confirm_cf_order"
    description = (
        "SOLO CONSUMIDOR FINAL. Cuando el cliente ACEPTA la cotización hecha con "
        "consumidor_final=true, ya confirmaste la dirección (o que retira) y la forma de "
        "pago (efectivo o transferencia): confirmá vos el pedido con esta tool. Si devuelve "
        "ok, el pedido YA ESTÁ CONFIRMADO (no digas 'pendiente de Joaquín'). Si devuelve "
        "not_confirmed, seguí el camino normal: escalate_to_joaco para que lo confirme él."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del cliente."},
            "order_id": {"type": "integer", "description": "ID de la cotización (create_sale_order)."},
            "payment": {"type": "string", "enum": list(PAYMENTS),
                        "description": "efectivo | transferencia"},
        },
        "required": ["partner_id", "order_id", "payment"],
    }

    def _problems(self, env, partner, order):
        problems = []
        if order.partner_id.commercial_partner_id != partner.commercial_partner_id:
            problems.append("la cotización es de otro cliente")
        if order.state not in ('draft', 'sent'):
            problems.append(f"la cotización está en estado {order.state}")
        if order.pricelist_id.name != CF_PRICELIST:
            problems.append("no está cotizada a precio de consumidor final")
        if 'cristal_customer_type' in partner._fields and partner.cristal_customer_type == 'negocio':
            problems.append("el cliente figura como negocio")
        pickup = getattr(order, 'cristal_delivery_mode', False) == 'retiro'
        if not pickup:
            zone = env['cristal.agent.circuit'].sudo().classify_city(partner.city)
            if zone.get('kind') != 'rio_cuarto':
                problems.append(f"envío fuera de Río Cuarto / Las Higueras ({partner.city or 'sin localidad'})")
            if not (partner.street or '').strip():
                problems.append("falta la dirección de entrega")
        # v1.49.2: solo productos físicos. El envío de consumidor final (método 14) usa el
        # servicio "Envío a domicilio GRATIS (Kit Cloro)", que quedó marcado con
        # seguimiento de stock: sin esto Claudio no confirmaba ningún pedido con envío.
        for line in order.order_line.filtered(
                lambda l: l.product_id.is_storable and l.product_id.type != 'service'
                and not getattr(l, 'is_delivery', False)):
            if line.product_id.free_qty < line.product_uom_qty:
                problems.append(f"no hay stock suficiente de {line.product_id.display_name}")
        if not order.order_line.filtered(lambda l: not getattr(l, 'is_delivery', False)):
            problems.append("la cotización no tiene productos")
        return problems

    def _execute(self, env, run=None, partner_id=None, order_id=None, payment=None, **kwargs):
        partner = env['res.partner'].sudo().browse(int(partner_id or 0))
        order = env['sale.order'].sudo().browse(int(order_id or 0))
        if not partner.exists() or not order.exists():
            return {"error": "partner_id u order_id no existen"}
        if payment not in PAYMENTS:
            return {"ok": False, "not_confirmed": True,
                    "message_for_bot": "Por ahora solo se confirma solo con efectivo o transferencia. "
                                       "Preguntale cuál prefiere."}
        problems = self._problems(env, partner, order)
        if problems:
            return {"ok": False, "not_confirmed": True, "problems": problems,
                    "message_for_bot": (
                        "NO lo confirmé: " + "; ".join(problems) + ". Si se puede resolver con el "
                        "cliente (dirección, otro producto con stock, retiro), resolvelo y volvé a "
                        "llamar. Si no, seguí el camino normal: escalate_to_joaco para que lo "
                        "confirme él.")}
        order.message_post(body=f"Confirmado por Claudio (consumidor final). Pago: {PAYMENTS[payment]}.")
        order.action_confirm()
        _logger.info("✅ Claudio confirmó %s (%s, %s)", order.name, partner.name, payment)
        try:
            config = env['cristal.agent.config'].sudo().get_active()
            if config and config.internal_channel_id:
                config.internal_channel_id.sudo().with_context(from_cristal_agent=True).message_post(
                    body=(f"🛒 Claudio confirmó el pedido {order.name} de {partner.name} "
                          f"(consumidor final): ${order.amount_total:,.0f}, pago "
                          f"{PAYMENTS[payment].lower()}, "
                          f"{'retira en el local' if order.cristal_delivery_mode == 'retiro' else 'envío a ' + (partner.street or '')}."
                          ).replace(',', '.'),
                    message_type='comment', subtype_xmlid='mail.mt_comment')
        except Exception:  # noqa: BLE001 — el aviso no frena la venta
            _logger.exception("No pude avisar en el canal interno la confirmación de %s", order.name)
        pickup = order.cristal_delivery_mode == 'retiro'
        return {
            "ok": True, "confirmed": True, "order_name": order.name, "total": order.amount_total,
            "message_for_bot": (
                f"Pedido {order.name} CONFIRMADO. Decile al cliente que quedó confirmado, el total "
                f"y la forma de pago ({PAYMENTS[payment].lower()}"
                + ("; pasale los datos para transferir de la KB" if payment == 'transferencia' else '')
                + "). " + ("Retira en San Martín 2350 en el horario oficial (día + fecha)."
                           if pickup else
                           "Envío: el reparto es por la mañana; decile que le avisamos el día de "
                           "entrega (no prometas día ni hora).")),
        }
