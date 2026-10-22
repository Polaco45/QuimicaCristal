# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    cristal_fallback_fiscal_position_id = fields.Many2one(
        'account.fiscal.position', string='Posición fiscal si el cliente no tiene',
        domain="[('company_id', '=', id)]",
        help='Se aplica en ventas y facturas de clientes sin posición fiscal: define '
             'los impuestos y el diario (por ejemplo, Ventas X).',
    )

    def _cristal_sale_fiscal_position(self, fiscal_position):
        """Posición fiscal efectiva de una venta: la del documento o la de reemplazo."""
        self.ensure_one()
        return fiscal_position or self.cristal_fallback_fiscal_position_id

    def _cristal_sale_journal(self, fiscal_position):
        """Diario de venta que corresponde a la posición fiscal (o vacío)."""
        self.ensure_one()
        journal = self._cristal_sale_fiscal_position(fiscal_position).cristal_sale_journal_id
        return journal if journal.company_id == self else self.env['account.journal']
