# -*- coding: utf-8 -*-
from odoo import models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _prepare_invoice_vals(self):
        # Manda la posición fiscal, no el diario elegido en la caja.
        vals = super()._prepare_invoice_vals()
        journal = self.company_id._cristal_sale_journal(self.fiscal_position_id)
        if journal:
            vals['journal_id'] = journal.id
            if self.invoice_journal_id != journal:
                self.invoice_journal_id = journal
        return vals
