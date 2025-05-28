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

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PosCrossSelling(models.Model):
    """Model Pos Cross-Selling Products"""
    _name = 'pos.cross.selling'
    _description = 'POS Cross-Selling'
    _rec_name = 'product_id'

    product_id = fields.Many2one(
        'product.product',
        domain=[('available_in_pos', '=', 'True')],
        required=True,
        string='Product Name',
        help="Product details"
    )
    active = fields.Boolean(
        string='Active',
        help="To check the cross selling is active or not",
        default=True
    )
    pos_cross_product_ids = fields.One2many(
        'pos.cross.selling.line',
        'pos_cross_product_id',
        string='Pos Cross products',
        help="Pos Cross products"
    )

    @api.constrains('product_id')
    def _check_product_id(self):
        """Avoid multiple creation of cross-selling for the same product"""
        for rec in self:
            pos = self.env['pos.cross.selling'].search(
                [('product_id', '=', rec.product_id.id)])
            if len(pos) > 1:
                raise ValidationError(_('Already exists a cross product for "%s".') % rec.product_id.name)

    @api.constrains('pos_cross_product_ids')
    def _check_pos_cross_product_ids(self):
        """Ensure there is at least one cross-selling line"""
        for rec in self:
            if len(rec.pos_cross_product_ids) < 1:
                raise ValidationError(_("Please add at least one cross product line."))

    @api.model
    def get_cross_selling_products(self, product_id):
        """Get cross-selling products with prices based on the active POS pricelist"""
        cross = self.env['pos.cross.selling'].search(
            [('product_id', '=', product_id)], limit=1)
        vals = []

        # Buscar la lista de precios activa del POS
        pos_config = self.env['pos.config'].search([('active', '=', True)], limit=1)
        pricelist = pos_config.pricelist_id

        for rec in cross.pos_cross_product_ids:
            product = rec.product_id.with_context(pricelist=pricelist.id)
            price = product.price

            vals.append({
                'id': product.id,
                'image': '/web/image?model=product.product&field=image_128&id=' + str(product.id),
                'name': product.name,
                'symbol': product.currency_id.symbol,
                'price': round(price, 2),
                'selected': False
            })
        return vals
