# -*- coding: utf-8 -*-
from odoo import api, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.depends('partner_id')
    def _compute_fiscal_position_id(self):
        super()._compute_fiscal_position_id()
        for order in self:
            if order.partner_id and not order.fiscal_position_id:
                order.fiscal_position_id = order.company_id._cristal_sale_fiscal_position(
                    order.fiscal_position_id, order.partner_id)

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        journal = self.company_id._cristal_sale_journal(self.fiscal_position_id, self.partner_id)
        if journal:
            vals['journal_id'] = journal.id
        return vals
