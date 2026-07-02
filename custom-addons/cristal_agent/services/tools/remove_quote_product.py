# -*- coding: utf-8 -*-
"""
Tool: remove_quote_product

Quita uno o más productos de la ÚNICA cotización (sale.order draft) del cliente.
Se usa cuando el cliente pide sacar/eliminar un producto de su presupuesto
("sacame el desengrasante", "no quiero la lavandina", etc.).

Complementa a create_sale_order (que agrega/mergea). Acá se elimina la línea.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class RemoveQuoteProduct(AgentTool):
    name = "remove_quote_product"

    # Mismo piso que create_sale_order
    COMPRA_MIN = 50000.0
    COMPRA_PISO = 39990.0

    description = (
        "Quita un producto de la cotización (draft) del cliente. Usalo cuando el "
        "cliente pide SACAR/eliminar algo del presupuesto. Pasale partner_id y el "
        "producto a quitar (product_id o product_name; el nombre matchea contra las "
        "líneas que YA están en la cotización). Devuelve el nuevo total y avisa si "
        "queda por debajo del mínimo/piso de compra."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del partner cliente."},
            "product_id": {"type": "integer", "description": "ID exacto del producto a quitar (opcional)."},
            "product_name": {
                "type": "string",
                "description": "Nombre/parte del producto a quitar (matchea contra las líneas de la cotización).",
            },
        },
        "required": ["partner_id"],
    }

    def _execute(self, env, run=None, partner_id=None, product_id=None,
                 product_name=None, **kwargs):
        if not partner_id:
            return {"error": "partner_id es obligatorio"}
        if not (product_id or product_name):
            return {"error": "Pasá product_id o product_name (qué producto sacar)."}

        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        # Buscar la cotización draft del cliente (misma lógica que create_sale_order)
        Lead = env['crm.lead'].sudo()
        opp = Lead.search([
            ('partner_id', '=', partner.id),
            ('type', '=', 'opportunity'),
            ('active', '=', True),
            ('stage_id', 'not in', [4, 13]),
        ], limit=1, order='create_date desc')
        order = None
        if opp:
            order = env['sale.order'].sudo().search([
                ('opportunity_id', '=', opp.id),
                ('state', '=', 'draft'),
            ], order='create_date desc', limit=1)
        if not order:
            return {
                "error": f"{partner.name} no tiene una cotización abierta (draft) "
                         f"de la cual sacar productos.",
            }

        # Encontrar las líneas a quitar
        if product_id:
            to_remove = order.order_line.filtered(
                lambda l: l.product_id.id == int(product_id))
        else:
            words = [w.lower() for w in product_name.split() if len(w) > 1]
            def _match(line):
                nm = (line.product_id.display_name or '').lower()
                return all(w in nm for w in words) if words else False
            to_remove = order.order_line.filtered(_match)

        if not to_remove:
            disponibles = [l.product_id.display_name for l in order.order_line]
            return {
                "error": f"No encontré '{product_id or product_name}' en la cotización "
                         f"{order.name}.",
                "productos_en_cotizacion": disponibles,
            }

        removed = [l.product_id.display_name for l in to_remove]
        try:
            order.write({'order_line': [(2, l.id) for l in to_remove]})
        except Exception as e:
            _logger.exception("Error quitando líneas de %s: %s", order.name, e)
            return {"error": f"No pude quitar el producto: {e}"}

        total = order.amount_total
        line_details = [{
            'product': l.product_id.display_name,
            'qty': l.product_uom_qty,
            'subtotal': l.price_subtotal,
        } for l in order.order_line]

        try:
            opp.message_post(body=(
                "Claudio quitó de la cotización <b>%s</b>: %s. Nuevo total: $%s." % (
                    order.name, ', '.join(removed), '{:,.0f}'.format(total))))
        except Exception:
            pass

        # Avisos de mínimo (si quedó vacía o por debajo del piso)
        warning = None
        if not order.order_line:
            warning = ("La cotización quedó VACÍA. Preguntale al cliente qué querés "
                       "cotizar o qué modificar.")
        elif total < self.COMPRA_PISO:
            warning = (f"OJO: el total quedó en ${total:,.0f}, por debajo del piso de "
                       f"${self.COMPRA_PISO:,.0f}. No se puede enviar así. Comunicá el "
                       f"mínimo (${self.COMPRA_MIN:,.0f}) y hacé upsell.")
        elif total < self.COMPRA_MIN:
            warning = (f"El total quedó en ${total:,.0f} (mínimo ${self.COMPRA_MIN:,.0f}). "
                       f"Se puede enviar, pero comunicá el mínimo y ofrecé sumar algo.")

        return {
            "ok": True,
            "order_id": order.id,
            "order_name": order.name,
            "removed": removed,
            "total_amount": total,
            "lines": line_details,
            "warning": warning,
            "summary": (
                f"Quité {', '.join(removed)} de {order.name}. "
                f"Nuevo total: ${total:,.2f}. "
                f"{'⚠️ ' + warning if warning else ''}"),
        }
