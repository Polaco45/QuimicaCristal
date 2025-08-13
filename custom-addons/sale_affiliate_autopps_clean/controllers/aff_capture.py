
# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class AffiliateCaptureController(http.Controller):

    @http.route(['/sale_affiliate_autopps/capture'], type='json', auth='public', website=True, csrf=False)
    def capture(self, key=None):
        """Persist affiliate key on the current draft sale order (cart).
        Does nothing if there's no active cart.
        """
        so = request.website.sale_get_order()
        if not so:
            return {'ok': False, 'reason': 'no_order'}
        if not key:
            # try cookie or url param just in case
            key = request.httprequest.cookies.get('x_affiliate_key') or request.params.get('aff_key')
        if not key:
            return {'ok': False, 'reason': 'no_key'}
        so.sudo().write({'x_affiliate_key': key})
        return {'ok': True}
