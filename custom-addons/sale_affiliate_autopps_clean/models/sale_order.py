# -*- coding: utf-8 -*-
from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_affiliate_key = fields.Char(string="Affiliate Key", help="Captured affiliate tracking key from the website URL or cookie.")