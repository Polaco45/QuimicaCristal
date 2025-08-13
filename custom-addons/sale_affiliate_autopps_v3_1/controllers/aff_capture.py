# -*- coding: utf-8 -*-
import logging
from odoo.addons.website_sale.controllers.main import WebsiteSale as WebsiteSaleBase
from odoo.http import request
from odoo import http

_logger = logging.getLogger(__name__)

def _log(msg):
    try:
        _logger.info("[sale_affiliate_autopps] %s", msg)
    except Exception:
        pass

class WebsiteSale(WebsiteSaleBase):

    def _extract_aff_key(self):
        aff_key = request.params.get("aff_key") or request.httprequest.args.get("aff_key")
        if aff_key:
            return aff_key
        cookies = request.httprequest.cookies
        for k in cookies.keys():
            if k.startswith("affkey_") and len(k) > 7:
                return k.split("affkey_", 1)[1]
        for name in ["aff_key", "affiliate_key", "wk_affiliate_key", "wk_affkey", "affiliate"]:
            if name in cookies and cookies.get(name):
                return cookies.get(name)
        return None

    def _set_order_aff_key_from_anywhere(self):
        so = request.website.sale_get_order()
        if not so:
            return
        if so.sudo().x_affiliate_key:
            return
        aff_key = self._extract_aff_key()
        if not aff_key:
            return
        so.sudo().x_affiliate_key = aff_key
        _log(f"SO {so.name if so else ''}: persistido x_affiliate_key={aff_key} desde cookie/url.")

    @http.route([
        "/shop",
        "/shop/page/<int:page>",
        "/shop/category/<model('product.public.category'):category>",
        "/shop/category/<model('product.public.category'):category>/page/<int:page>",
    ], type="http", auth="public", website=True, sitemap=WebsiteSaleBase.sitemap_shop)
    def shop(self, page=0, category=None, search="", min_price=0.0, max_price=0.0, ppg=False, **post):
        res = super().shop(page=page, category=category, search=search, min_price=min_price, max_price=max_price, ppg=ppg, **post)
        self._set_order_aff_key_from_anywhere()
        return res

    @http.route(['/shop/product/<model("product.template"):product>'], type="http", auth="public", website=True, sitemap=True)
    def product(self, product, category="", search="", **kwargs):
        res = super().product(product=product, category=category, search=search, **kwargs)
        self._set_order_aff_key_from_anywhere()
        return res

    @http.route(['/shop/cart'], type="http", auth="public", website=True, sitemap=False)
    def cart(self, **post):
        res = super().cart(**post)
        self._set_order_aff_key_from_anywhere()
        return res

    @http.route(['/shop/address'], type="http", auth="public", website=True, sitemap=False)
    def address(self, **post):
        res = super().address(**post)
        self._set_order_aff_key_from_anywhere()
        return res

    @http.route(['/shop/confirm_order'], type="http", auth="public", website=True, sitemap=False)
    def confirm_order(self, **post):
        res = super().confirm_order(**post)
        self._set_order_aff_key_from_anywhere()
        return res
