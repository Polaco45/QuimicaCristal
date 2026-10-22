# -*- coding: utf-8 -*-
from odoo import api, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _cristal_applies(self):
        self.ensure_one()
        return (
            self.move_type in ('out_invoice', 'out_refund')
            and self.state == 'draft'
            and not self.posted_before
            and self.partner_id
        )

    @api.depends('partner_id', 'move_type')
    def _compute_fiscal_position_id(self):
        super()._compute_fiscal_position_id()
        for move in self:
            if move._cristal_applies() and not move.fiscal_position_id:
                move.fiscal_position_id = move.company_id._cristal_sale_fiscal_position(
                    move.fiscal_position_id, move.partner_id)

    @api.depends('fiscal_position_id')
    def _compute_journal_id(self):
        super()._compute_journal_id()
        for move in self:
            if not move._cristal_applies():
                continue
            journal = move.company_id._cristal_sale_journal(move.fiscal_position_id, move.partner_id)
            if journal and move.journal_id != journal:
                move.journal_id = journal
