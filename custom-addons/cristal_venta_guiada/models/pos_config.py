# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    cristal_vg_enabled = fields.Boolean(string='Venta guiada')
    cristal_vg_fiscal_position_ids = fields.Many2many(
        'account.fiscal.position', 'cristal_vg_config_fiscal_position_rel', 'config_id', 'fiscal_position_id',
        string='Posiciones fiscales de consumidor final',
        help='La venta guiada solo se muestra en tickets con estas posiciones fiscales. Vacío: en todos.')
    cristal_vg_impulse_product_ids = fields.Many2many(
        'product.product', 'cristal_vg_config_impulse_rel', 'config_id', 'product_id',
        string='Productos de caja', domain=[('available_in_pos', '=', True)],
        help='Al ir a cobrar se ofrece el primero de esta lista que tenga stock y no esté en el ticket.')
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
            slots, loose = [], 0.0
            for combo in product.combo_ids:
                items = combo.combo_item_ids.product_id
                if not items:
                    continue
                slots.append(items.ids)
                loose += max(pricelist._get_product_price(item, 1.0) for item in items)
            if slots:
                combos.append({
                    'product_id': product.id,
                    'name': product.name,
                    'price': pricelist._get_product_price(product, 1.0),
                    'loose': loose,
                    'slots': slots,
                })

        impulse = [p.id for p in self.cristal_vg_impulse_product_ids if in_stock(p)]
        return {
            'enabled': True,
            'cf_fp_ids': self.cristal_vg_fiscal_position_ids.ids,
            'suggestions': suggestions,
            'combos': combos,
            'impulse': impulse,
            'start_categ_id': self.cristal_vg_start_categ_id.id,
        }
