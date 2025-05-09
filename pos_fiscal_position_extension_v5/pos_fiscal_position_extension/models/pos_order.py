from odoo import models, api

class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def create_from_ui(self, orders, draft=False):
        for order in orders:
            if 'data' in order and order['data'].get('selected_journal_id'):
                self = self.with_context(journal_id=order['data']['selected_journal_id'])
        return super().create_from_ui(orders, draft=draft)

    def _prepare_invoice_vals(self):
        vals = super()._prepare_invoice_vals()
        if self._context.get('journal_id'):
            vals['journal_id'] = self._context['journal_id']
        return vals
