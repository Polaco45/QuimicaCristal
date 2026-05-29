# -*- coding: utf-8 -*-
"""Tool: check_stock — verifica stock disponible."""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class CheckStock(AgentTool):
    name = "check_stock"
    description = (
        "Verifica el stock disponible (qty_available - qty_reserved) de un producto."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "product_id": {"type": "integer"},
        },
        "required": ["product_id"],
    }

    def _execute(self, env, run=None, product_id=None, **kwargs):
        if not product_id:
            return {"error": "product_id es obligatorio"}

        product = env['product.product'].sudo().browse(int(product_id))
        if not product.exists():
            return {"error": f"product_id={product_id} no existe"}

        return {
            "ok": True,
            "product_id": product.id,
            "name": product.name,
            "qty_available": product.qty_available or 0.0,
            "virtual_available": product.virtual_available or 0.0,
            "incoming_qty": product.incoming_qty or 0.0,
            "outgoing_qty": product.outgoing_qty or 0.0,
            "uom": product.uom_id.name if product.uom_id else '',
        }
