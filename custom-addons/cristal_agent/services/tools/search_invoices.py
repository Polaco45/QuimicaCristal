# -*- coding: utf-8 -*-
"""Tool: search_invoices — busca facturas del cliente."""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class SearchInvoices(AgentTool):
    name = "search_invoices"
    description = (
        "Busca facturas de venta (account.move tipo 'out_invoice') de un cliente. "
        "Útil cuando piden 'mi factura del mes pasado' o para revisar deudas."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer"},
            "limit": {"type": "integer", "default": 10},
            "only_unpaid": {"type": "boolean", "default": False},
        },
        "required": ["partner_id"],
    }

    def _execute(self, env, run=None, partner_id=None, limit=10, only_unpaid=False, **kwargs):
        if not partner_id:
            return {"error": "partner_id es obligatorio"}

        domain = [
            ('partner_id', '=', int(partner_id)),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
        ]
        if only_unpaid:
            domain.append(('payment_state', 'in', ['not_paid', 'partial']))

        invoices = env['account.move'].sudo().search(
            domain,
            order='invoice_date desc',
            limit=int(limit or 10),
        )

        results = []
        for inv in invoices:
            results.append({
                'id': inv.id,
                'name': inv.name,
                'invoice_date': str(inv.invoice_date) if inv.invoice_date else '',
                'invoice_date_due': str(inv.invoice_date_due) if inv.invoice_date_due else '',
                'amount_untaxed': inv.amount_untaxed,
                'amount_total': inv.amount_total,
                'amount_residual': inv.amount_residual,
                'payment_state': inv.payment_state,
            })

        return {"ok": True, "count": len(results), "invoices": results}
