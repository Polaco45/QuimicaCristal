# -*- coding: utf-8 -*-
from odoo import models


class ProductCombo(models.Model):
    _inherit = 'product.combo'

    def _load_pos_data(self, data):
        # Odoo reparte el precio del combo entre sus productos según base_price
        # (precio de lista mínimo), pero acá casi todos los productos tienen precio
        # de lista 0/1 y el precio real está en la lista de la caja.
        res = super()._load_pos_data(data)
        config = self.env['pos.config'].browse(data['pos.config']['data'][0]['id'])
        pricelist = config.pricelist_id
        if not pricelist:
            return res
        for rec in res['data']:
            items = self.browse(rec['id']).combo_item_ids.product_id
            prices = [pricelist._get_product_price(p, 1.0) for p in items]
            if prices:
                rec['base_price'] = min(prices)
        return res
