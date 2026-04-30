# -*- coding: utf-8 -*-
from lxml import etree
from odoo import models, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def get_views(self, views, options=None):
        res = super().get_views(views, options)
        if not self.env.user.has_group('fv_hide_cost_price.groups_view_cost_price'):
            for view_type in res.get('views', {}):
                view = res['views'][view_type]
                if view.get('arch'):
                    arch = etree.fromstring(view['arch'])
                    for field in arch.xpath("//field[@name='standard_price']"):
                        field.set('column_invisible', '1')
                    view['arch'] = etree.tostring(arch, encoding='unicode')
        return res
