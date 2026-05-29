# -*- coding: utf-8 -*-
"""Tool: generate_quote_pdf — genera PDF de una sale.order."""
import base64
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class GenerateQuotePdf(AgentTool):
    name = "generate_quote_pdf"
    description = (
        "Genera el PDF de una sale.order (cotización o presupuesto) y lo guarda como "
        "ir.attachment. Devuelve el attachment_id para que después lo puedas adjuntar "
        "a un mensaje WhatsApp via send_whatsapp_with_attachment "
        "(o referenciarlo en algún flujo)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "sale_order_id": {"type": "integer"},
        },
        "required": ["sale_order_id"],
    }

    def _execute(self, env, run=None, sale_order_id=None, **kwargs):
        if not sale_order_id:
            return {"error": "sale_order_id es obligatorio"}

        order = env['sale.order'].sudo().browse(int(sale_order_id))
        if not order.exists():
            return {"error": f"sale.order id={sale_order_id} no existe"}

        # Generar el reporte
        try:
            report = env.ref('sale.action_report_saleorder')
            pdf_content, _content_type = report.sudo()._render_qweb_pdf(
                'sale.action_report_saleorder', [order.id]
            )
        except Exception as e:
            return {"error": f"No se pudo generar PDF: {e}"}

        # Guardar como attachment
        try:
            attachment = env['ir.attachment'].sudo().create({
                'name': f"Cotizacion_{order.name}.pdf",
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': 'sale.order',
                'res_id': order.id,
                'mimetype': 'application/pdf',
            })
        except Exception as e:
            return {"error": f"No se pudo guardar attachment: {e}"}

        return {
            "ok": True,
            "attachment_id": attachment.id,
            "filename": attachment.name,
            "summary": f"PDF de cotización {order.name} generado (attachment_id={attachment.id})",
        }
