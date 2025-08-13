
# -*- coding: utf-8 -*-
from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_affiliate_key = fields.Char(string='Affiliate Key', index=True, copy=False)
