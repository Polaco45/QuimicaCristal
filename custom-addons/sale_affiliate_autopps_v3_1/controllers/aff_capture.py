
# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request
# Import the native WebsiteSale to keep the same route and behavior
from odoo.addons.website_sale.controllers.main import WebsiteSale

_logger = logging.getLogger(__name__)


class WebsiteSaleAff(WebsiteSale):
    """Keep the exact same behavior but ensure we never call a missing super() method.

    Odoo 18 moved/removed `confirm_order` in some editions; calling super().confirm_order
    raises AttributeError and breaks checkout with a 500. Here we guard that call and
    gracefully fall back to the expected redirect flow (`/shop/payment`), keeping the
    affiliate key persistence intact.
    """

    def _set_order_aff_key_from_anywhere(self):
        # Read key from querystring or cookies (support both names for safety)
        httpreq = request.httprequest
        aff_key = (
            request.params.get("x_affiliate_key")
            or request.params.get("aff_key")
            or httpreq.args.get("x_affiliate_key")
            or httpreq.args.get("aff_key")
            or httpreq.cookies.get("x_affiliate_key")
            or httpreq.cookies.get("aff_key")
        )
        if not aff_key:
            return
        order = request.website.sale_get_order(force_create=False)
        if order:
            try:
                order.sudo().write({"x_affiliate_key": aff_key})
                _logger.info("[sale_affiliate_autopps] SO %s: persistido x_affiliate_key=%s desde cookie/url.",
                             order.name, aff_key)
            except Exception:
                _logger.exception("No se pudo persistir x_affiliate_key en la orden.")

    @http.route(['/shop/confirm_order'], type='http', auth='public', website=True, sitemap=False)
    def confirm_order(self, **post):
        """Mirror native behavior without breaking when super().confirm_order is absent.

        - Always persist the affiliate key before leaving the step.
        - If the native method exists, delegate to it.
        - Otherwise, follow the standard flow: redirect to payment when the order exists,
          or back to cart if not.
        """
        # Persist affiliation key (idempotent)
        try:
            self._set_order_aff_key_from_anywhere()
        except Exception:
            _logger.exception("Fallo al setear affiliate key en confirm_order.")

        # Prefer the native implementation when available
        method = getattr(super(), "confirm_order", None)
        if callable(method):
            return method(**post)

        # Fallback: keep UX identical to default flow
        order = request.website.sale_get_order(force_create=False)
        if order:
            return request.redirect("/shop/payment")
        return request.redirect("/shop/cart")
