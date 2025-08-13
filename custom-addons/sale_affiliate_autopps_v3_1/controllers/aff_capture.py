
# -*- coding: utf-8 -*-
import logging
from urllib.parse import urlparse, parse_qs

from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

_logger = logging.getLogger(__name__)


class WebsiteSaleAff(WebsiteSale):
    """
    Mantiene el flujo original del checkout, captura y persiste x_affiliate_key
    en la orden en todos los pasos relevantes y evita el 500 de /shop/confirm_order
    cuando el método nativo no existe.
    """

    # ---- helpers ----

    def _capture_aff_key(self):
        """Try to read the affiliate key from params, cookies or Referer URL."""
        httpreq = request.httprequest

        # 1) direct params (GET/POST)
        aff_key = (
            request.params.get("x_affiliate_key")
            or request.params.get("aff_key")
            or httpreq.args.get("x_affiliate_key")
            or httpreq.args.get("aff_key")
        )

        # 2) cookies (varios nombres por compatibilidad)
        if not aff_key:
            aff_key = (
                httpreq.cookies.get("x_affiliate_key")
                or httpreq.cookies.get("aff_key")
                or httpreq.cookies.get("affiliate_key")
                or httpreq.cookies.get("affiliate")
            )

        # 3) Referer (por si el param vino en la página del producto)
        if not aff_key:
            ref = httpreq.headers.get("Referer")
            if ref:
                try:
                    q = parse_qs(urlparse(ref).query)
                    aff_key = (
                        (q.get("x_affiliate_key") or [None])[0]
                        or (q.get("aff_key") or [None])[0]
                        or (q.get("affiliate") or [None])[0]
                    )
                except Exception:  # pragma: no cover
                    _logger.exception("No se pudo parsear Referer para aff_key")

        return aff_key

    def _persist_aff_on_order(self, aff_key):
        """Write x_affiliate_key on current website order (idempotent)."""
        if not aff_key:
            return False
        order = request.website.sale_get_order(force_create=False)
        if not order:
            return False
        try:
            if not getattr(order, "x_affiliate_key", None) or order.x_affiliate_key != aff_key:
                order.sudo().write({"x_affiliate_key": aff_key})
                _logger.info("[sale_affiliate_autopps] SO %s: persistido x_affiliate_key=%s desde cookie/url/referrer.",
                             order.name, aff_key)
            return True
        except Exception:  # pragma: no cover
            _logger.exception("No se pudo persistir x_affiliate_key en la orden.")
            return False

    def _maybe_set_cookie(self, response, aff_key):
        """Set cookie to keep the key across steps."""
        if not aff_key:
            return
        try:
            # 30 días
            response.set_cookie("x_affiliate_key", aff_key, max_age=60 * 60 * 24 * 30, path="/", samesite="Lax")
        except Exception:  # pragma: no cover
            _logger.debug("No se pudo setear cookie x_affiliate_key.")

    # ---- routes (cart / checkout / payment / confirm) ----

    @http.route(['/shop/cart'], type='http', auth='public', website=True, sitemap=False)
    def cart(self, **post):
        aff_key = self._capture_aff_key()
        self._persist_aff_on_order(aff_key)
        resp = super().cart(**post)
        self._maybe_set_cookie(resp, aff_key)
        return resp

    @http.route(['/shop/checkout'], type='http', auth='public', website=True, sitemap=False)
    def checkout(self, **post):
        aff_key = self._capture_aff_key()
        self._persist_aff_on_order(aff_key)
        method = getattr(super(), "checkout", None)
        resp = method(**post) if callable(method) else request.redirect("/shop/cart")
        self._maybe_set_cookie(resp, aff_key)
        return resp

    @http.route(['/shop/payment'], type='http', auth='public', website=True, sitemap=False)
    def payment(self, **post):
        aff_key = self._capture_aff_key()
        self._persist_aff_on_order(aff_key)
        method = getattr(super(), "payment", None)
        if not callable(method):
            method = getattr(super(), "shop_payment", None)  # compatibilidad
        resp = method(**post) if callable(method) else request.redirect("/shop/cart")
        self._maybe_set_cookie(resp, aff_key)
        return resp

    @http.route(['/shop/confirm_order'], type='http', auth='public', website=True, sitemap=False)
    def confirm_order(self, **post):
        # Persistimos por las dudas también aquí
        aff_key = self._capture_aff_key()
        self._persist_aff_on_order(aff_key)

        # Si existe la implementación nativa, la usamos
        method = getattr(super(), "confirm_order", None)
        if callable(method):
            resp = method(**post)
            self._maybe_set_cookie(resp, aff_key)
            return resp

        # Fallback seguro sin 500
        order = request.website.sale_get_order(force_create=False)
        resp = request.redirect("/shop/payment" if order else "/shop/cart")
        self._maybe_set_cookie(resp, aff_key)
        return resp
