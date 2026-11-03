# -*- coding: utf-8 -*-
"""
Tool: confirm_order (v1.53)

Claudio confirma solo los pedidos MAYORISTAS que cumplen la lista de control; el resto
sigue yendo a Joaco ("PEDIDO PARA CONFIRMAR"). Joaco (03/11/2026, "avanza con todo esto",
sobre la propuesta del plan): Río Cuarto / Las Higueras o retiro en planta, hasta el monto
de config, con stock de lo envasado, sin facturas vencidas, con dirección, bidones
resueltos y pago en efectivo o transferencia. Los pedidos de la ruta del camión siguen con
Joaco (dependen de la salida).

Antes, el 35 % de los pases a Joaco eran "¿se confirmó mi pedido?" de clientes que ya
habían dicho que sí (14 días: 254 pases, caso Florencia S06925).
"""
import logging
from datetime import date

from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

PAYMENTS = {'efectivo': 'Efectivo (contra entrega o al retirar)',
            'transferencia': 'Transferencia anticipada'}
MAYORISTA_PRICELIST = 'Lista Mayorista'
MAX_DISCOUNT = 20.0


@ToolRegistry.register
class ConfirmOrder(AgentTool):
    name = "confirm_order"
    description = (
        "MAYORISTA. Cuando el cliente ACEPTA la cotización y ya confirmaste la dirección "
        "exacta (o que retira en planta), los bidones y la forma de pago (efectivo o "
        "transferencia): confirmá vos el pedido con esta tool. Si devuelve ok, el pedido YA "
        "ESTÁ CONFIRMADO (no digas 'pendiente de Joaquín'). Si devuelve not_confirmed, "
        "resolvé lo que diga o seguí el camino normal: escalate_to_joaco('PEDIDO PARA "
        "CONFIRMAR …') para que lo confirme él."
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

    def _overdue_invoices(self, env, partner):
        Move = env['account.move'].sudo()
        return Move.search([
            ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('invoice_date_due', '<', date.today()),
            ('commercial_partner_id', '=', partner.commercial_partner_id.id)], limit=3)

    def _problems(self, env, config, partner, order):
        from .search_products import is_made_to_order
        problems = []
        if not config.auto_confirm_enabled:
            problems.append("la confirmación automática está apagada")
        if order.partner_id.commercial_partner_id != partner.commercial_partner_id:
            problems.append("la cotización es de otro cliente")
        if order.state not in ('draft', 'sent'):
            problems.append(f"la cotización está en estado {order.state}")
        if order.pricelist_id.name != MAYORISTA_PRICELIST:
            problems.append("no está cotizada con la Lista Mayorista")
        if order.route_departure_id:
            problems.append("es un pedido de la ruta del camión: lo confirma Joaquín")
        limit = config.auto_confirm_max_amount or 0.0
        if limit and order.amount_untaxed > limit:
            problems.append(f"supera el monto de confirmación automática "
                            f"(${order.amount_untaxed:,.0f} > ${limit:,.0f})".replace(',', '.'))
        pickup = getattr(order, 'cristal_delivery_mode', False) == 'retiro'
        if not pickup:
            zone = partner.agent_zone
            if zone not in ('rio_cuarto', 'las_higueras'):
                kind = env['cristal.agent.circuit'].sudo().classify_city(partner.city).get('kind')
                if kind != 'rio_cuarto':
                    problems.append(f"envío fuera de Río Cuarto / Las Higueras "
                                    f"({partner.city or 'sin localidad'})")
            if not (partner.street or '').strip():
                problems.append("falta la dirección de entrega")
        lines = order.order_line.filtered(
            lambda l: not l.display_type and l.product_id and not getattr(l, 'is_delivery', False))
        if not lines:
            problems.append("la cotización no tiene productos")
        granel = lines.filtered(lambda l: is_made_to_order(l.product_id)
                                and 'granel' in (l.product_id.name or '').lower())
        if granel and not order.cristal_bidones_answered:
            problems.append("falta confirmar los bidones de recambio (create_sale_order con bidones_nuevos)")
        for line in lines:
            p = line.product_id
            if p.is_storable and p.type != 'service' and not is_made_to_order(p):
                if p.free_qty < line.product_uom_qty:
                    problems.append(f"no hay stock suficiente de {p.display_name}")
            if (line.discount or 0.0) > MAX_DISCOUNT:
                problems.append(f"descuento mayor al 20% en {p.display_name}")
        overdue = self._overdue_invoices(env, partner)
        if overdue:
            problems.append("tiene facturas vencidas sin pagar (" + ', '.join(overdue.mapped('name'))
                            + "): lo confirma Joaquín")
        return problems

    def _execute(self, env, run=None, partner_id=None, order_id=None, payment=None, **kwargs):
        partner = env['res.partner'].sudo().browse(int(partner_id or 0))
        order = env['sale.order'].sudo().browse(int(order_id or 0))
        if not partner.exists() or not order.exists():
            return {"error": "partner_id u order_id no existen"}
        if payment not in PAYMENTS:
            return {"ok": False, "not_confirmed": True,
                    "message_for_bot": "Solo se confirma solo con efectivo o transferencia. "
                                       "Preguntale cuál prefiere."}
        config = env['cristal.agent.config'].sudo().get_active()
        problems = self._problems(env, config, partner, order)
        if problems:
            return {"ok": False, "not_confirmed": True, "problems": problems,
                    "message_for_bot": (
                        "NO lo confirmé: " + "; ".join(problems) + ". Si se puede resolver con "
                        "el cliente (dirección, bidones, retiro, otro producto), resolvelo y "
                        "volvé a llamar. Si no, escalá: escalate_to_joaco('PEDIDO PARA "
                        "CONFIRMAR — …') con el número de cotización, y decile al cliente que "
                        "queda pendiente de confirmación de Joaquín.")}
        pickup = order.cristal_delivery_mode == 'retiro'
        order.with_context(from_cristal_agent=True).message_post(
            body=f"Confirmado por Claudio (mayorista, lista de control OK). Pago: {PAYMENTS[payment]}.")
        order.with_context(from_cristal_agent=True).action_confirm()
        _logger.info("✅ Claudio confirmó %s (%s, %s)", order.name, partner.name, payment)
        try:
            if config.internal_channel_id:
                config.internal_channel_id.sudo().with_context(from_cristal_agent=True).message_post(
                    body=(f"🛒 Claudio confirmó el pedido {order.name} de {partner.name} "
                          f"(mayorista): ${order.amount_untaxed:,.0f} sin IVA, pago "
                          f"{PAYMENTS[payment].lower()}, "
                          f"{'retira en planta' if pickup else 'envío a ' + (partner.street or '') + ', ' + (partner.city or '')}."
                          ).replace(',', '.'),
                    message_type='comment', subtype_xmlid='mail.mt_comment')
        except Exception:  # noqa: BLE001 — el aviso no frena la venta
            _logger.exception("No pude avisar en el canal interno la confirmación de %s", order.name)
        return {
            "ok": True, "confirmed": True, "order_name": order.name,
            "total": order.amount_total, "subtotal_sin_iva": order.amount_untaxed,
            "message_for_bot": (
                f"Pedido {order.name} CONFIRMADO. Decile al cliente que quedó confirmado, con el "
                f"resumen en el orden de la regla de oro 9 (productos, bidones, total, pago "
                f"{PAYMENTS[payment].lower()}"
                + ("; pasale los datos para transferir TEXTUALES de la KB" if payment == 'transferencia' else '')
                + "). " + ("Retira en San Martín 2350 en el horario oficial (día + fecha) con sus "
                           "bidones vacíos con tapa." if pickup else
                           "Envío: el reparto en Río Cuarto es por la mañana y nunca los miércoles; "
                           "decile que le avisamos el día de entrega (no prometas día ni hora).")
                + " NO escales a Joaco por este pedido: ya está confirmado y avisado."),
        }
