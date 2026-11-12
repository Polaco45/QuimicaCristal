# -*- coding: utf-8 -*-
"""
Tool: generate_invoice_pdf (v1.66, conversión punto 10)

El cliente pide "mandame la factura": Claudio la busca con search_invoices y la manda por
WhatsApp. Usa el PDF que ya tiene la factura (el que sale con el CAE); si no hay, lo genera.
Solo facturas publicadas del mismo cliente.
"""
import base64
import logging

from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class GenerateInvoicePdf(AgentTool):
    name = "generate_invoice_pdf"
    description = (
        "Devuelve el PDF de una factura del cliente para mandársela por WhatsApp. Buscala "
        "antes con search_invoices y pasá su id. Después mandala con send_whatsapp usando "
        "el attachment_id que te devuelve (una línea de texto: 'Le paso la factura FA-A …')."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del cliente."},
            "invoice_id": {"type": "integer", "description": "ID de la factura (search_invoices)."},
        },
        "required": ["partner_id", "invoice_id"],
    }

    def _execute(self, env, run=None, partner_id=None, invoice_id=None, **kwargs):
        partner = env['res.partner'].sudo().browse(int(partner_id or 0))
        inv = env['account.move'].sudo().browse(int(invoice_id or 0))
        if not partner.exists() or not inv.exists():
            return {"error": "partner_id o invoice_id no existen"}
        if inv.move_type not in ('out_invoice', 'out_refund') or inv.state != 'posted':
            return {"error": "Solo se mandan facturas o notas de crédito publicadas."}
        if inv.commercial_partner_id != partner.commercial_partner_id:
            return {"error": "Esa factura es de otro cliente: no la mandes."}
        att = inv.message_main_attachment_id
        if not att or att.mimetype != 'application/pdf':
            try:
                pdf, _ = env['ir.actions.report'].sudo()._render_qweb_pdf(
                    'account.account_invoices', [inv.id])
            except Exception as e:  # noqa: BLE001
                return {"error": f"No se pudo generar el PDF: {e}"}
            att = env['ir.attachment'].sudo().create({
                'name': f"{(inv.name or 'Factura').replace('/', '-')}.pdf",
                'type': 'binary', 'datas': base64.b64encode(pdf),
                'res_model': 'account.move', 'res_id': inv.id,
                'mimetype': 'application/pdf'})
        def ars(x):
            return '$' + f"{x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        return {"ok": True, "attachment_id": att.id, "filename": att.name,
                "summary": (f"PDF de la factura {inv.name} listo (attachment_id={att.id}). "
                            f"Total {ars(inv.amount_total)}, saldo {ars(inv.amount_residual)}.")}
