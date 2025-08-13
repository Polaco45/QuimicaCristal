# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class SaleAffiliateCaptureController(http.Controller):

    @http.route('/sale_affiliate_autopps/persist', type='json', auth='public', website=True, csrf=False)
    def persist_affiliate_key(self, key=None, **kwargs):
        """Persist the affiliate key on the current website sale order.

        This route is intentionally *non-invasive* and does not override any Website
        Sale routes. It simply stores the key on the sale.order currently bound to
        the visitor's session (creating one only if there is already a cart or
        checkout is in progress).
        """
        if not key:
            return {"ok": False, "reason": "no_key"}

        # Only persist when there is a cart/checkout context to avoid creating empty SOs.
        order = request.website.sale_get_order(force_create=False)
        if not order:
            # No cart yet: nothing to persist.
            return {"ok": False, "reason": "no_order"}

        order = order.sudo()
        order.write({"x_affiliate_key": key})
        request.env.cr.commit()  # ensure it's saved even if called early

        _logger = request.env['ir.logging']
        request.env['ir.logging'].create({
            'name': 'sale_affiliate_autopps_clean',
            'type': 'server',
            'level': 'INFO',
            'dbname': request.env.cr.dbname,
            'message': f"[sale_affiliate_autopps] SO {order.name}: persisted x_affiliate_key={key}",
            'path': __name__,
            'line': '0',
            'func': 'persist_affiliate_key',
        })
        return {"ok": True, "order": order.name, "key": key}