
# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class AffiliateCapture(http.Controller):

    @http.route('/sale_affiliate_autopps/capture', type='json', auth='public', website=True, csrf=False)
    def capture(self, aff_key=None, **kwargs):
        """Persiste la affiliate key en la cookie y en el sale.order de la sesión.

        NO toca rutas del checkout.

        La cookie se setea por JS (este endpoint sólo escribe en la orden).
        """
        key = aff_key or (request.httprequest.args.get('aff_key') if request.httprequest else None)
        if not key:
            return {'ok': False, 'reason': 'missing_key'}

        order = None
        try:
            order = request.website.sale_get_order()
        except Exception:
            # fuera de website context
            order = None

        if order and not order.x_affiliate_key:
            order.sudo().write({'x_affiliate_key': key})
            _logger.info('[sale_affiliate_autopps] SO %s: persistido x_affiliate_key=%s desde cookie/url.', order.name, key)
        return {'ok': True}
