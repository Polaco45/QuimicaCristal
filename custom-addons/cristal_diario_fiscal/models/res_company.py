# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    cristal_fallback_fiscal_position_id = fields.Many2one(
        'account.fiscal.position', string='Posición fiscal sin responsabilidad AFIP',
        domain="[('company_id', '=', id)]",
        help='Para ventas a clientes sin posición fiscal ni tipo de responsabilidad '
             'AFIP (por ejemplo, Ventas X).',
    )
    cristal_responsible_fiscal_position_id = fields.Many2one(
        'account.fiscal.position', string='Posición fiscal con responsabilidad AFIP',
        domain="[('company_id', '=', id)]",
        help='Para ventas a clientes sin posición fiscal que tienen cargado cualquier '
             'tipo de responsabilidad AFIP (por ejemplo, IVA 21%).',
    )

    def _cristal_sale_fiscal_position(self, fiscal_position, partner):
        """Posición fiscal efectiva de una venta: la del documento o, si no tiene,
        la que sale del tipo de responsabilidad AFIP del cliente."""
        self.ensure_one()
        if fiscal_position or not partner:
            return fiscal_position
        if partner.commercial_partner_id.l10n_ar_afip_responsibility_type_id:
            return self.cristal_responsible_fiscal_position_id
        return self.cristal_fallback_fiscal_position_id

    def _cristal_sale_journal(self, fiscal_position, partner):
        """Diario de venta que corresponde a la posición fiscal (o vacío)."""
        self.ensure_one()
        journal = self._cristal_sale_fiscal_position(fiscal_position, partner).cristal_sale_journal_id
        return journal if journal.company_id == self else self.env['account.journal']
