# -*- coding: utf-8 -*-
#################################################################################
# Author : Webkul Software Pvt. Ltd. (<https://webkul.com/>:wink:
# Copyright(c): 2015-Present Webkul Software Pvt. Ltd.
# All Rights Reserved.
#
#
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#
# You should have received a copy of the License along with this program.
# If not, see <https://store.webkul.com/license.html/>;
#################################################################################
import logging
_logger = logging.getLogger(__name__)

from odoo import api, fields, models, _
from odoo.http import request

from odoo.exceptions import UserError

class SaleOrderInherit(models.Model):
    _inherit = 'sale.order'


    affiliate_partner_id = fields.Many2one('res.partner', string='Affiliate Partner', domain="[('is_affiliate', '=', True),('res_affiliate_key', '!=', False)]")
    affiliate_program_id = fields.Many2one('affiliate.program', string='Affiliate Program')




    def show_affiliate_visits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Visits',
            'res_model': 'affiliate.visit',
            'view_mode': 'list,form',
            'domain': [('sales_order_line_id','in', self.order_line.ids)],
            'target': 'current',
        }





    def action_confirm(self):
        res = super().action_confirm()
        self.create_affiliate_visit()
        return res
    

    def create_affiliate_visit(self):
        AffVisit = self.env['affiliate.visit']
        affiliate_partner = self.affiliate_partner_id
        if not affiliate_partner:
            return
        affiliate_key = affiliate_partner.res_affiliate_key
        all_visits = AffVisit.sudo().search([])
        for rec in self:
            for s in rec.order_line:
                existing_visit = all_visits.filtered(lambda v: v.sales_order_line_id.id == s.id and v.state != 'cancel')
                if len(existing_visit) > 0:
                    continue
                cancelled_visit = all_visits.filtered(lambda v: v.sales_order_line_id.id == s.id and v.state == 'cancel')
                if hasattr(s, 'is_delivery') and s.is_delivery:
                    continue
                product_tmpl_id = s.product_id.product_tmpl_id.id
                visit_vals = {
                    'affiliate_method':'pps',
                    'currency_id': rec.pricelist_id.currency_id.id if rec.pricelist_id else self.company_id.currency_id.id,
                    'affiliate_key':affiliate_key,
                    'affiliate_partner_id':affiliate_partner.id,
                    'url':"",
                    'ip_address':request.httprequest.environ['REMOTE_ADDR'],
                    'type_id':product_tmpl_id,
                    'affiliate_type': 'product',
                    'type_name':s.product_id.id,
                    'sales_order_line_id':s.id,
                    'convert_date':fields.datetime.now(),
                    'affiliate_program_id': rec.affiliate_program_id.id,
                    'product_quantity' : s.product_uom_qty,
                    'is_converted':True
                }
                if cancelled_visit:
                    visit_vals.update({
                        'state': 'draft'
                    })
                    cancelled_visit.write(visit_vals)
                else:
                    aff_visit = AffVisit.sudo().create(visit_vals)

    
    def action_cancel(self):
        res = super().action_cancel()
        if res:
            all_visits = self.env['affiliate.visit'].sudo().search([])
            all_visits.filtered(lambda v: v.sales_order_line_id.id in self.order_line.ids and v.state != 'cancel')
            all_visits.write({'state':'cancel'})

        return res