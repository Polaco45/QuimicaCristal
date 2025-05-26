# -*- coding: utf-8 -*-
from odoo import models, fields

class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    x_pos_payment_reference = fields.Char(
        string="Referencia Pago POS",
        readonly=True,
        help="Referencia del pago registrada en el Punto de Venta."
    )
