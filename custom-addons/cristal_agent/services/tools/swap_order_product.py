# -*- coding: utf-8 -*-
"""
Tool: swap_order_product (v1.81.2)

Joaco (24/11/2026, caso Tefi S07488): "que Guillermo le pueda decir 'che, no hay esto,
consultá si no le podemos mandar tal cosa'; Claudio consulte, modifique y vuelva a avisarle a
Guillermo".

Cambia (o saca) un producto de un pedido YA CONFIRMADO que todavía no se entregó, y le avisa
al depósito por WhatsApp que el pedido cambió. El remito se ajusta solo.
"""
import logging

from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class SwapOrderProduct(AgentTool):
    name = "swap_order_product"
    description = (
        "Pedido CONFIRMADO sin entregar: reemplaza un producto por otro (o lo saca) cuando "
        "el cliente aceptó el cambio, típicamente después de una novedad del depósito "
        "(\"no hay jabón frutilla, ¿le sirve blanco?\" → el cliente dijo que sí). Pasale "
        "order_id, el producto a cambiar (old_product_id u old_product_name) y el nuevo "
        "(new_product_id, o vacío para SACARLO). Por defecto mantiene el mismo precio "
        "(keep_price=true). Le avisa solo al depósito (Guillermo) del cambio. Para "
        "cotizaciones sin confirmar usá create_sale_order / remove_quote_product."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "order_id": {"type": "integer", "description": "ID del pedido confirmado."},
            "old_product_id": {"type": "integer", "description": "Producto a cambiar."},
            "old_product_name": {"type": "string",
                                 "description": "Parte del nombre del producto a cambiar."},
            "new_product_id": {"type": "integer",
                               "description": "Producto nuevo (vacío = sacar el producto)."},
            "keep_price": {"type": "boolean",
                           "description": "Mismo precio que el producto original (default true)."},
        },
        "required": ["order_id"],
    }

    def _execute(self, env, run=None, order_id=None, old_product_id=None,
                 old_product_name=None, new_product_id=None, keep_price=True, **kwargs):
        order = env['sale.order'].sudo().browse(int(order_id or 0)).exists()
        if not order:
            return {"error": f"order_id={order_id} no existe"}
        if order.state != 'sale':
            return {"error": f"{order.name} no está confirmado ({order.state}): usá "
                             f"create_sale_order / remove_quote_product."}
        lines = order.order_line.filtered(
            lambda l: not l.display_type and l.product_uom_qty > 0)
        if old_product_id:
            lines = lines.filtered(lambda l: l.product_id.id == int(old_product_id))
        elif old_product_name:
            key = old_product_name.lower()
            lines = lines.filtered(lambda l: key in (l.product_id.display_name or '').lower())
        else:
            return {"error": "Pasá old_product_id u old_product_name."}
        if len(lines) != 1:
            return {"error": f"Encontré {len(lines)} renglones que coinciden en {order.name}: "
                             f"pasá old_product_id exacto.",
                    "lines": [{"product_id": l.product_id.id, "name": l.product_id.display_name,
                               "qty": l.product_uom_qty} for l in order.order_line
                              if not l.display_type and l.product_uom_qty > 0]}
        line = lines
        if line.qty_delivered:
            return {"error": f"{line.product_id.display_name} ya se entregó: no se puede cambiar."}
        old_name = line.product_id.display_name
        qty, price, disc = line.product_uom_qty, line.price_unit, line.discount
        new = env['product.product'].sudo().browse(int(new_product_id or 0)).exists()
        if new:
            vals = {'order_id': order.id, 'product_id': new.id, 'product_uom_qty': qty,
                    'sequence': line.sequence}
            nl = env['sale.order.line'].sudo().create(vals)
            if keep_price is not False:
                nl.write({'price_unit': price, 'discount': disc})
        line.write({'product_uom_qty': 0})
        change = (f"{old_name} → {new.display_name}" if new else f"se sacó {old_name}")
        order.message_post(body=f"🔁 Cambio aceptado por el cliente: {change}.",
                           subtype_xmlid='mail.mt_note')
        notified = False
        try:
            from .. import pickup_staff as ps
            staff = ps.staff_partner(env)
            if staff and (order.cristal_delivery_mode == 'retiro'
                          or order.cristal_pickup_staff_asked_at):
                res = ps._send(env, staff, f"✅ {order.partner_id.name} aceptó el cambio en "
                                           f"{order.name}: {change}. El pedido ya está "
                                           f"actualizado.")
                notified = bool(res.get('ok'))
        except Exception:  # noqa: BLE001 — el cambio ya quedó hecho
            _logger.exception("No pude avisarle al depósito el cambio de %s", order.name)
        return {"ok": True, "order_name": order.name, "change": change,
                "new_total": order.amount_total, "depot_notified": notified,
                "message_for_bot": (
                    f"Listo: en {order.name} quedó {change}. Total ${order.amount_total:,.0f}. "
                    + ("Ya le avisé al depósito. " if notified else "")
                    + "Confirmale al cliente en una línea.").replace(',', '.')}
