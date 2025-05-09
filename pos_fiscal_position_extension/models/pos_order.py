from odoo import models

class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _prepare_invoice_vals(self):
        vals = super()._prepare_invoice_vals()
        if self.session_id.config_id.module_pos_restaurant and hasattr(self, 'selected_journal_id'):
            vals['journal_id'] = self.selected_journal_id
        elif self._context.get('journal_id'):
            vals['journal_id'] = self._context['journal_id']
        return vals

    def _prepare_invoice(self):
        invoice = super()._prepare_invoice()
        # Si se pasó el journal_id desde el frontend, aplicarlo
        if self._context.get('journal_id'):
            invoice.journal_id = self._context['journal_id']
        return invoice
