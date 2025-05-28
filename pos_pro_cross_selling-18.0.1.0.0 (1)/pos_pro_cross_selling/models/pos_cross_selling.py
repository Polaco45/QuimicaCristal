# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author: Adarsh K(<https://www.cybrosys.com>)
#
#    This program is free software: you can modify
#    it under the terms of the GNU Affero General Public License (AGPL) as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
################################################################################
from odoo import api, models, fields, _

class PosCrossSelling(models.Model):
    """Model Pos Cross-Selling Products"""
    _name = 'pos.cross.selling'
    _description = 'POS Cross-Selling'
    _rec_name = 'product_id'

    product_id = fields.Many2one(
        'product.product',
        domain=[('available_in_pos', '=', True)],
        required=True,
        string='Product Name',
        help="Base product for cross-selling suggestions"
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help="Activate or deactivate this cross-selling record"
    )
    pos_cross_product_ids = fields.One2many(
        'pos.cross.selling.line',
        'pos_cross_product_id',
        string='POS Cross products',
        help="Products suggested as cross-sell for the base product"
    )
    # ────────────────────────────────────────────────────────────────
    #   M É T O D O   C O R R E G I D O
    # ────────────────────────────────────────────────────────────────
    @api.model
    def get_cross_selling_products(self, *args, **kwargs):
        """
        Devuelve los productos de cross-selling con el precio calculado
        según la lista de precios activa del POS y el cliente de la sesión.
        El método acepta *args porque el RPC le pasa:  [], product_id
        """
        # args = (ids_list, product_id)  ← nosotros sólo usamos el último
        if not args:
            return []
        product_id = args[-1]

        cross = self.search([('product_id', '=', product_id)], limit=1)
        if not cross:
            return []

        # ───────────────── Obtener lista de precios activa ───────────
        pricelist = False
        if self.env.context.get('pricelist'):
            pricelist = self.env['product.pricelist'].browse(
                self.env.context['pricelist'])

        if not pricelist:
            session = self.env['pos.session'].search(
                [('user_id', '=', self.env.uid), ('state', '=', 'opened')],
                limit=1
            )
            if session:
                pricelist = session.config_id.pricelist_id
                partner = session.partner_id
            else:
                partner = False
        else:
            partner = False

        if not pricelist:
            # Fallback a la primera lista de precios disponible
            pricelist = self.env['product.pricelist'].search([], limit=1)

        # ───────────────── Construir respuesta ───────────────────────
        vals = []
        for line in cross.pos_cross_product_ids:
            prod = line.product_id
            # Cantidad 1 (ajustar si querés otra)
            price = pricelist._get_product_price(prod, 1, partner)

            vals.append({
                'id': prod.id,
                'image': f"/web/image?model=product.product&field=image_128&id={prod.id}",
                'name': prod.name,
                'symbol': pricelist.currency_id.symbol,
                'price': round(price, 2),
                'selected': False,
            })
        return vals
