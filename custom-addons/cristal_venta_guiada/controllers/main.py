# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class CristalVentaGuiadaWeb(http.Controller):

    @http.route('/cristal/vg/ladder', type='json', auth='public', website=True)
    def ladder(self, product_id, line_id=None, **kw):
        """Pasos de la escalera para el producto recién agregado al carrito."""
        product = request.env['product.product'].sudo().browse(int(product_id)).exists()
        order = request.website.sale_get_order()
        if not product or not order:
            return {'steps': []}
        if product.type == 'combo':
            return {'native': True, 'steps': []}
        Sugg = request.env['cristal.vg.suggestion'].sudo()
        steps = Sugg.website_ladder(order, product, int(line_id) if line_id else None)
        if steps:
            request.env['cristal.vg.event'].sudo().log_events([{
                'order_uuid': 'web-%s' % order.id, 'trigger_product_id': product.id,
                'product_id': s['product']['id'], 'kind': s['kind'], 'channel': 'web',
            } for s in steps])
        return {'steps': steps, 'order_id': order.id}

    @http.route('/cristal/vg/cart', type='json', auth='public', website=True)
    def cart_popup(self, **kw):
        """Popup "Completá tu compra" del carrito."""
        order = request.website.sale_get_order()
        if not order or not order.order_line:
            return {}
        return request.env['cristal.vg.suggestion'].sudo().website_cart_popup(order)

    @http.route('/cristal/vg/accept', type='json', auth='public', website=True)
    def accept(self, step, **kw):
        """Aplica el paso aceptado sobre el carrito y lo registra."""
        order = request.website.sale_get_order()
        if not order:
            return {}
        product = request.env['product.product'].sudo().browse(int(step['product']['id'])).exists()
        kind = step.get('kind')
        if kind == 'qty' and step.get('line_id'):
            order._cart_update(product_id=product.id, line_id=int(step['line_id']), set_qty=int(step['qty']))
        elif kind == 'size':
            order._cart_update(product_id=product.id, add_qty=1)
            if step.get('replace_line_id'):
                small = order.order_line.filtered(lambda l: l.id == int(step['replace_line_id']))
                if small:
                    order._cart_update(product_id=small.product_id.id, line_id=small.id,
                                       set_qty=max(0, small.product_uom_qty - 1))
        elif kind == 'complement':
            order._cart_update(product_id=product.id, add_qty=1)
        request.env['cristal.vg.event'].sudo().log_events([{
            'order_uuid': 'web-%s' % order.id, 'trigger_product_id': step.get('trigger_id') or False,
            'product_id': product.id, 'kind': kind, 'accepted': True, 'channel': 'web',
            'amount': step.get('saving') or step['product'].get('price') or 0.0,
        }])
        request.session['website_sale_cart_quantity'] = order.cart_quantity
        return {'cart_quantity': order.cart_quantity, 'amount_total': order.amount_total}
