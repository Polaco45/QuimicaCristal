# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    cristal_vg_enabled = fields.Boolean(string='Venta guiada')
    cristal_vg_fiscal_position_ids = fields.Many2many(
        'account.fiscal.position', 'cristal_vg_config_fiscal_position_rel', 'config_id', 'fiscal_position_id',
        string='Posiciones fiscales de consumidor final',
        help='La venta guiada solo se muestra en tickets con estas posiciones fiscales. Vacío: en todos.')
    cristal_vg_checkout_product_id = fields.Many2one(
        'product.product', string='Promo de caja', domain=[('type', '=', 'combo')],
        help='Combo que se ofrece para cerrar el ticket (por ejemplo, 2 por $1.999): se anuncia '
             'mientras se carga y, si no se ofreció, al ir a cobrar.')
    cristal_vg_start_categ_id = fields.Many2one('pos.category', string='Categoría al abrir')

    def _cristal_vg_payload(self):
        """Lo que la caja necesita para la venta guiada (se manda al abrir el POS)."""
        self.ensure_one()
        if not self.cristal_vg_enabled:
            return {'enabled': False}
        pricelist = self.pricelist_id
        Sugg = self.env['cristal.vg.suggestion'].sudo()

        suggestions = {}
        stock_cache = {}

        def in_stock(product):
            if product.id not in stock_cache:
                stock_cache[product.id] = product.qty_available > 0
            return stock_cache[product.id]

        for s in Sugg.search([]):
            if not s.product_id.available_in_pos or not in_stock(s.product_id):
                continue
            items = suggestions.setdefault(s.trigger_product_id.id, [])
            if len(items) < 3:
                items.append([s.product_id.id, 'manual' if s.manual else s.kind, s.text or ''])

        combos = []
        combo_products = self.env['product.product'].search([
            ('type', '=', 'combo'), ('available_in_pos', '=', True)])
        for product in combo_products:
            slots = [c.combo_item_ids.product_id.ids for c in product.combo_ids if c.combo_item_ids]
            if slots:
                combos.append({
                    'product_id': product.id,
                    'name': product.name,
                    'price': pricelist._get_product_price(product, 1.0),
                    'slots': slots,
                })

        checkout = False
        promo = self.cristal_vg_checkout_product_id
        if promo and promo.available_in_pos:
            names = []
            for item in promo.combo_ids[:1].combo_item_ids.product_id:
                # Una sola vez por producto aunque tenga varios aromas.
                name = item.product_tmpl_id.name
                if name not in names:
                    names.append(name)
            checkout = {
                'product_id': promo.id,
                'name': promo.name,
                'price': pricelist._get_product_price(promo, 1.0),
                'items': names,
            }
        return {
            'enabled': True,
            'cf_fp_ids': self.cristal_vg_fiscal_position_ids.ids,
            'suggestions': suggestions,
            'combos': combos,
            'checkout': checkout,
            'start_categ_id': self.cristal_vg_start_categ_id.id,
        }
