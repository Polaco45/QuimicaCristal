# -*- coding: utf-8 -*-
# This module and its content is copyright of Technaureus Info Solutions Pvt. Ltd. - ©
# Technaureus Info Solutions Pvt. Ltd 2024. All rights reserved.
from odoo import models, _lt
from odoo.http import request


class Website(models.Model):
    """Inherits the 'website' model to customize the checkout process."""
    _inherit = 'website'

    def _get_checkout_steps(self, current_step=None):
        """Determine the steps of the checkout process based on various conditions."""
        self.ensure_one()
        is_extra_step_active = self.viewref('website_sale.extra_info').active
        redirect_to_sign_in = self.account_on_checkout == 'mandatory' and self.is_public_user()
        min_sale_price = request.env['ir.config_parameter'].sudo().get_param(
            'tis_min_sale_price.min_sale_price')
        minimum_sale_price = float(min_sale_price)
        tax_info = request.env['ir.config_parameter'].sudo().get_param(
            'tis_min_sale_price.tax_type')
        order = request.website.sale_get_order()

        cart_url = f'{"/web/login?redirect=" if redirect_to_sign_in else ""}/shop/checkout?express=1'
        if minimum_sale_price:
            if tax_info == 'tax_excluded':
                if order and order.amount_untaxed <= minimum_sale_price:
                    cart_url = '/shop/cart'
            elif tax_info == 'tax_included':
                if order and order.amount_total <= minimum_sale_price:
                    cart_url = '/shop/cart'
        else:
            cart_url = cart_url
        steps = [(['website_sale.cart'], {
            'name': _lt("Review Order"),
            'current_href': '/shop/cart',
            'main_button': _lt("Sign In") if redirect_to_sign_in else _lt("Checkout"),
            'main_button_href': cart_url,
            'back_button':  _lt("Continue shopping"),
            'back_button_href': '/shop',
        }), (['website_sale.checkout', 'website_sale.address'], {
            'name': _lt("Shipping"),
            'current_href': '/shop/checkout',
            'main_button': _lt("Confirm"),
            'main_button_href': f'{"/shop/extra_info" if is_extra_step_active else "/shop/confirm_order"}',
            'back_button':  _lt("Back to cart"),
            'back_button_href': '/shop/cart',
        })]
        if is_extra_step_active:
            steps.append((['website_sale.extra_info'], {
                'name': _lt("Extra Info"),
                'current_href': '/shop/extra_info',
                'main_button': _lt("Continue checkout"),
                'main_button_href': '/shop/confirm_order',
                'back_button':  _lt("Return to shipping"),
                'back_button_href': '/shop/checkout',
            }))
        steps.append((['website_sale.payment'], {
            'name': _lt("Payment"),
            'current_href': '/shop/payment',
            'back_button':  _lt("Back to cart"),
            'back_button_href': '/shop/cart',
        }))

        if current_step:
            return next(step for step in steps if current_step in step[0])[1]
        else:
            return steps
