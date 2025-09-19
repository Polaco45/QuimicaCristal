# -*- coding: utf-8 -*-
from odoo import api, fields, models

class AffiliateVisit(models.Model):
    _inherit = "affiliate.visit"

    customer_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        compute='_compute_customer_id',
        store=True,
        readonly=True,
    )

    @api.depends('sales_order_line_id.order_id.partner_id', 'act_invoice_id.partner_id')
    def _compute_customer_id(self):
        for rec in self:
            partner = False
            if rec.sales_order_line_id and rec.sales_order_line_id.order_id:
                partner = rec.sales_order_line_id.order_id.partner_id
            if not partner and rec.act_invoice_id:
                partner = rec.act_invoice_id.partner_id
            rec.customer_id = partner.id if partner else False
