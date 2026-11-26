# -*- coding: utf-8 -*-
"""
Tool: switch_order_to_pickup (v1.82.2)

Joaco (26/11/2026, caso Leila S07183): el pedido estaba confirmado para el camión y la
clienta dijo "lo paso a retirar hoy". Claudio le contestó "te confirmo el monto final hoy"
y nadie hizo nada: hubo que sacarle el flete, pasarlo a retiro y avisarle a Guillermo a mano.
"Debería haberlo hecho Claudio."

Pasa un pedido CONFIRMADO y sin entregar a RETIRO EN PLANTA: saca el flete de la ruta /
envío a domicilio, saca la salida del camión, pone "Retirar en el Local", fecha de hoy, y le
pide la hora al depósito (Guillermo) por WhatsApp. Opcionalmente saca productos que el
cliente ya no quiere (old_product_names).
"""
import logging

from odoo import fields

from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class SwitchOrderToPickup(AgentTool):
    name = "switch_order_to_pickup"
    description = (
        "Pedido CONFIRMADO sin entregar que el cliente ahora quiere RETIRAR en planta "
        "(\"lo paso a buscar hoy\", \"mejor lo retiro\"). Lo pasa a retiro: saca el flete y "
        "la salida del camión, pone 'Retirar en el Local' con fecha de hoy y le pide la hora "
        "al depósito (Guillermo). Si el cliente dijo que algún producto ya no lo quiere, "
        "pasalo en remove_product_names. Devuelve el TOTAL NUEVO: decíselo al cliente en el "
        "mismo mensaje (con el alias crilimp si paga por transferencia). NO prometas "
        "'te confirmo el monto después': usá esta herramienta y decile el monto ya. Para "
        "cotizaciones sin confirmar usá create_sale_order con retiro."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "order_id": {"type": "integer", "description": "ID del pedido confirmado."},
            "remove_product_names": {
                "type": "array", "items": {"type": "string"},
                "description": "Productos que el cliente ya no quiere (parte del nombre)."},
        },
        "required": ["order_id"],
    }

    def _execute(self, env, run=None, order_id=None, remove_product_names=None, **kwargs):
        order = env['sale.order'].sudo().browse(int(order_id or 0)).exists()
        if not order:
            return {"error": f"order_id={order_id} no existe"}
        if order.state != 'sale':
            return {"error": f"{order.name} no está confirmado ({order.state}): para una "
                             f"cotización usá create_sale_order con retiro."}
        lines = order.order_line.filtered(lambda l: not l.display_type)
        if any(l.qty_delivered for l in lines):
            return {"error": f"{order.name} ya tiene productos entregados: no se puede pasar "
                             f"a retiro desde acá. Avisale al cliente que lo consultás."}
        if getattr(order, 'cristal_delivery_mode', '') == 'retiro' and \
                getattr(order, 'cristal_pickup_staff_asked_at', False):
            return {"ok": True, "already": True, "order_name": order.name,
                    "new_total": order.amount_total,
                    "message_for_bot": f"{order.name} ya estaba como retiro y el depósito ya "
                                       f"está avisado. Total ${order.amount_total:,.0f}."
                                       .replace(',', '.')}

        removed = []
        # 1) Productos que el cliente ya no quiere.
        for name in (remove_product_names or []):
            key = (name or '').strip().lower()
            if not key:
                continue
            match = lines.filtered(lambda l: l.product_uom_qty > 0 and
                                   key in (l.product_id.display_name or '').lower())
            for l in match:
                removed.append(l.product_id.display_name)
                l.product_uom_qty = 0
        # 2) Flete de la ruta y envío a domicilio.
        freight = lines.filtered(
            lambda l: l.product_uom_qty > 0 and (
                (l.product_id.default_code or '') == 'FLETE-ZONA'
                or getattr(l, 'is_delivery', False)))
        freight_amount = sum(freight.mapped('price_total'))
        for l in freight:
            if getattr(l, 'is_delivery', False):
                l.write({'price_unit': 0.0})
            else:
                l.product_uom_qty = 0
        # 3) Retiro, sin salida del camión, fecha de hoy.
        now = fields.Datetime.now()
        vals = {'cristal_delivery_mode': 'retiro', 'commitment_date': now}
        if 'route_departure_id' in order._fields:
            vals['route_departure_id'] = False
        if 'carrier_id' in order._fields:
            carrier = env['delivery.carrier'].sudo().search(
                [('name', 'ilike', 'retirar')], limit=1)
            if carrier:
                vals['carrier_id'] = carrier.id
        order.write(vals)
        order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')).write(
            {'scheduled_date': now})
        change = "pasó a RETIRO en planta"
        if freight_amount:
            change += f" (sin flete de ${freight_amount:,.0f})".replace(',', '.')
        if removed:
            change += "; se sacó: " + ", ".join(removed)
        order.message_post(body=f"🏬 El cliente lo retira: {change}.",
                           subtype_xmlid='mail.mt_note')
        # 4) Pedirle la hora al depósito.
        staff_asked = False
        try:
            from .. import pickup_staff as ps
            res = ps.ask_staff(env, order) or {}
            staff_asked = bool(res.get('ok'))
        except Exception:  # noqa: BLE001 — el cambio ya quedó hecho
            _logger.exception("No pude avisarle al depósito el retiro de %s", order.name)
        total = f"${order.amount_total:,.0f}".replace(',', '.')
        return {"ok": True, "order_name": order.name, "new_total": order.amount_total,
                "removed": removed, "freight_removed": freight_amount,
                "depot_notified": staff_asked,
                "message_for_bot": (
                    f"Listo: {order.name} {change}. TOTAL NUEVO {total}. Decile el total al "
                    f"cliente ahora (alias crilimp si transfiere). "
                    + ("El depósito ya está avisado y le confirma por acá la hora en que queda "
                       "listo." if staff_asked else
                       "No pude avisarle al depósito: decile que la hora se la confirmamos "
                       "por acá.")
                    + " Planta: San Martín 2350.")}
