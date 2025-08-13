# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

COOKIE_NAME = "aff_key"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 días

def _get_cookie_from_request():
    try:
        return request.httprequest.cookies.get(COOKIE_NAME)
    except Exception:
        return None

def _normalize_key(val):
    if not val:
        return None
    val = str(val).strip()
    # Permitimos solo alfanumérico + '-' + '_' para evitar keys sucias
    return "".join(ch for ch in val if ch.isalnum() or ch in "-_") or None

def _persist_aff_key_to_session_and_order(aff_key):
    """Guarda el aff_key en la sesión y en la venta abierta si existe.
    Nunca crea ni confirma orden acá; solo persiste el dato.
    """
    if not aff_key:
        return {"ok": False, "reason": "empty"}
    try:
        request.session["x_affiliate_key"] = aff_key
    except Exception:
        # Sesión puede no estar disponible en algunos contextos
        pass

    try:
        order = request.website.sale_get_order(force_create=False)
    except Exception:
        order = None

    if order and not order.x_affiliate_key:
        try:
            order.sudo().write({"x_affiliate_key": aff_key})
            _logger.info("[affiliate_autopps] SO %s: persistido x_affiliate_key=%s desde cookie/url.",
                         order.name, aff_key)
        except Exception as e:
            _logger.warning("No se pudo escribir x_affiliate_key en la orden: %s", e)

    return {"ok": True}

class AffCaptureController(http.Controller):

    @http.route("/sale_affiliate_autopps/capture", type="json", auth="public", website=True, csrf=False)
    def capture(self, aff_key=None, **kw):
        """Endpoint llamado por JS cuando detecta aff_key en URL o cookie.
        Guarda en sesión y, si hay una SO actual, lo escribe ahí.
        """
        # Si no vino en el body, lo intentamos leer de cookie
        key = _normalize_key(aff_key) or _normalize_key(_get_cookie_from_request())
        if not key:
            return {"ok": False, "reason": "no_key"}
        return _persist_aff_key_to_session_and_order(key)
