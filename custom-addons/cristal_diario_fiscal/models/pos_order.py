# -*- coding: utf-8 -*-
from odoo import fields, models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    cristal_journal_manual = fields.Boolean(
        string='Diario cambiado en la caja', readonly=True, copy=False,
        help='El vendedor cambió a mano el diario (y la posición fiscal) de esta '
             'venta en la pantalla de cobro, confirmando el cambio.',
    )

    def _prepare_invoice_vals(self):
        # Manda la posición fiscal de la venta, no el diario suelto: cuando el
        # vendedor cambia el diario en la caja se cambia la posición fiscal.
        vals = super()._prepare_invoice_vals()
        journal = self.company_id._cristal_sale_journal(self.fiscal_position_id, self.partner_id)
        if journal:
            vals['journal_id'] = journal.id
            if self.invoice_journal_id != journal:
                self.invoice_journal_id = journal
        return vals
