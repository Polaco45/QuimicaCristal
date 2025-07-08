# -*- coding: utf-8 -*-
# This module and its content is copyright of Technaureus Info Solutions Pvt. Ltd.
# - © Technaureus Info Solutions Pvt. Ltd 2024. All rights reserved.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """inherited res.config.settings and added min_sale_price and tax_type for website sale"""
    _inherit = 'res.config.settings'

    min_sale_price = fields.Float(string='Minimum Sale Price',
                                  config_parameter='tis_min_sale_price.min_sale_price')
    tax_type = fields.Selection([
        ('tax_included', 'Tax Included'),
        ('tax_excluded', 'Tax Excluded')], config_parameter='tis_min_sale_price.tax_type',
            default='tax_excluded')
