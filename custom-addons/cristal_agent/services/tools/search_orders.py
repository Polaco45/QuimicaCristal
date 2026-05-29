# -*- coding: utf-8 -*-
"""Tool: search_orders — busca órdenes de venta del cliente."""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class SearchOrders(AgentTool):
    name = "search_orders"
    description = (
        "Busca órdenes de venta (sale.order) de un cliente. Devuelve las últimas N "
        "con su estado, fecha, monto y líneas resumidas. Útil para preguntas tipo "
        "'¿cuándo me hacés mi último pedido?' o 'quiero pedir lo mismo que la vez pasada'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer"},
            "limit": {"type": "integer", "default": 5},
            "include_lines": {
                "type": "boolean",
                "description": "Si True, incluye las líneas de cada orden (productos + cantidades).",
                "default": True,
            },
        },
        "required": ["partner_id"],
    }

    def _execute(self, env, run=None, partner_id=None, limit=5, include_lines=True, **kwargs):
        if not partner_id:
            return {"error": "partner_id es obligatorio"}

        SaleOrder = env['sale.order'].sudo()
        orders = SaleOrder.search(
            [('partner_id', '=', int(partner_id))],
            order='date_order desc',
            limit=int(limit or 5),
        )

        results = []
        for o in orders:
            order_data = {
                'id': o.id,
                'name': o.name,
                'state': o.state,
                'date_order': str(o.date_order) if o.date_order else '',
                'amount_untaxed': o.amount_untaxed,
                'amount_total': o.amount_total,
                'invoice_status': o.invoice_status,
            }
            if include_lines:
                order_data['lines'] = [{
                    'product_id': line.product_id.id if line.product_id else 0,
                    'product_name': line.product_id.name if line.product_id else '',
                    'product_uom_qty': line.product_uom_qty,
                    'price_unit': line.price_unit,
                    'price_subtotal': line.price_subtotal,
                } for line in o.order_line]
            results.append(order_data)

        return {"ok": True, "count": len(results), "orders": results}
