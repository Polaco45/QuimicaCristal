import logging
from odoo import http, _
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

try:
    from odoo.addons.website_sale.controllers.main import WebsiteSale as WebsiteSaleController
except Exception:
    WebsiteSaleController = http.Controller

# En algunos temas/instalaciones, el JSON de métodos lo sirve payment.controllers.portal
try:
    from odoo.addons.payment.controllers.portal import PaymentPortal as PaymentPortalController
except Exception:
    PaymentPortalController = http.Controller


def _allowed_sets(order):
    c = order.carrier_id.sudo()
    return set(c.allowed_payment_method_ids.ids), set(c.allowed_payment_provider_ids.ids)


def _method_allowed(method, allowed_method_ids, allowed_provider_ids):
    # method puede ser record (payment.method) o dict JSON con 'id' y 'provider_id'
    if allowed_method_ids:
        mid = method.id if hasattr(method, "id") else int(method.get("id", 0))
        return mid in allowed_method_ids
    # por proveedor
    if hasattr(method, "provider_id"):
        pid = method.provider_id.id
    else:
        pid = int(method.get("provider_id") or 0)
    return (not allowed_provider_ids) or (pid in allowed_provider_ids)


def _filter_methods_any(obj, allowed_method_ids, allowed_provider_ids):
    # Recordset de payment.method
    if hasattr(obj, "filtered"):
        return obj.filtered(lambda m: _method_allowed(m, allowed_method_ids, allowed_provider_ids))
    # Lista de dicts JSON [{'id': .., 'provider_id': ..}, ...]
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return [m for m in obj if _method_allowed(m, allowed_method_ids, allowed_provider_ids)]
    return obj


class WebsiteSale(WebsiteSaleController):
    """Filtra SIEMPRE los métodos mostrados en /shop/payment, cubriendo
    los posibles nombres de clave que usan core/temas en 17/18.
    """

    def _apply_filter_to_values(self, values, order):
        c = order.carrier_id
        if not (c and c.restrict_payment_methods):
            return values

        allowed_method_ids, allowed_provider_ids = _allowed_sets(order)

        # 1) Providers (por si la plantilla los usara)
        providers = values.get("providers")
        if providers and hasattr(providers, "filtered"):
            if allowed_method_ids:
                # si se filtra por método, dejar solo providers con algún método permitido
                allowed_pids = set(m.provider_id.id for m in c.allowed_payment_method_ids)
                values["providers"] = providers.filtered(lambda p: p.id in allowed_pids)
            elif allowed_provider_ids:
                values["providers"] = providers.filtered(lambda p: p.id in allowed_provider_ids)

        # 2) Métodos: cubrir todas las variantes de clave
        for key in ("payment_methods", "methods", "available_methods", "available_payment_methods"):
            if key in values and values[key]:
                values[key] = _filter_methods_any(values[key], allowed_method_ids, allowed_provider_ids)

        return values

    # Hook usado por v16/v17
    def _get_shop_payment_values(self, order, **kwargs):
        values = super()._get_shop_payment_values(order, **kwargs)
        return self._apply_filter_to_values(values, order)

    # Hook usado por v18 (según instalación/tema)
    def _prepare_shop_payment_values(self, order, **kwargs):
        values = super()._prepare_shop_payment_values(order, **kwargs)
        return self._apply_filter_to_values(values, order)

    # Validación server-side
    @http.route(['/shop/payment/transaction'], type='json', auth='public', website=True, csrf=False)
    def shop_payment_transaction(self, **kwargs):
        order = request.website.sale_get_order()
        if order and order.carrier_id and order.carrier_id.restrict_payment_methods:
            allowed_method_ids, allowed_provider_ids = _allowed_sets(order)

            method_id = kwargs.get("payment_method_id")
            provider_id = kwargs.get("provider_id") or kwargs.get("acquirer_id") or kwargs.get("acquirer")

            if method_id:
                try:
                    mid = int(method_id)
                except Exception:
                    mid = 0
                if mid:
                    method = request.env["payment.method"].sudo().browse(mid)
                    if method.exists():
                        if allowed_method_ids and mid not in allowed_method_ids:
                            raise UserError(_("El método de pago seleccionado no está disponible para el método de entrega elegido."))
                        if not allowed_method_ids and allowed_provider_ids and method.provider_id.id not in allowed_provider_ids:
                            raise UserError(_("El método de pago seleccionado no está disponible para el método de entrega elegido."))

            if not method_id and provider_id:
                try:
                    pid = int(provider_id)
                except Exception:
                    pid = 0
                if pid:
                    if allowed_method_ids:
                        ok = any(m.provider_id.id == pid for m in order.carrier_id.allowed_payment_method_ids)
                        if not ok:
                            raise UserError(_("El método de pago seleccionado no está disponible para el método de entrega elegido."))
                    elif allowed_provider_ids and pid not in allowed_provider_ids:
                        raise UserError(_("El método de pago seleccionado no está disponible para el método de entrega elegido."))

        return super().shop_payment_transaction(**kwargs)


class PaymentPortal(PaymentPortalController):
    """Algunos frontends refrescan métodos por XHR; filtramos también el JSON."""
    @http.route(['/payment/payment_methods'], type='json', auth='public', website=True)
    def payment_methods(self, **kwargs):
        data = super().payment_methods(**kwargs)
        try:
            order = request.website.sale_get_order()
            c = order and order.carrier_id
            if not (order and c and c.restrict_payment_methods):
                return data

            allowed_method_ids, allowed_provider_ids = _allowed_sets(order)

            # data estructura típica: {'payment_methods': [ {id, provider_id, ...}, ... ], ...}
            for key in ("payment_methods", "methods", "available_methods", "available_payment_methods"):
                if key in data and data[key]:
                    data[key] = _filter_methods_any(data[key], allowed_method_ids, allowed_provider_ids)
        except Exception as e:
            _logger.warning("payment_methods filter skipped due to error: %s", e)
        return data
