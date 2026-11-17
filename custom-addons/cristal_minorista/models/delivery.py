# -*- coding: utf-8 -*-
"""Envío gratis por producto (v1.7.0, Joaco 17/11/2026: "hagamos que esta promo tenga envío
gratis", la promo de cloro 6 kg).

Se hace en `rate_shipment`, que es lo que usan la web, el asistente "Agregar envío" de la
cotización y Claudio (create_sale_order): si el pedido trae alguno de los productos del
parámetro `cristal_minorista.envio_gratis_productos` (ids separados por coma), el envío
cotiza $0, sin que nadie tenga que acordarse de aplicar una promoción a mano."""
import logging

from odoo import models

_logger = logging.getLogger(__name__)

FREE_SHIPPING_PARAM = 'cristal_minorista.envio_gratis_productos'


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    def _cristal_free_shipping_product_ids(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(FREE_SHIPPING_PARAM, '') or ''
        ids = set()
        for chunk in raw.replace(';', ',').split(','):
            chunk = chunk.strip()
            if chunk.isdigit():
                ids.add(int(chunk))
        return ids

    def rate_shipment(self, order):
        res = super().rate_shipment(order)
        try:
            free_ids = self._cristal_free_shipping_product_ids()
            if free_ids and res and res.get('success') and order and any(
                    line.product_id.id in free_ids and line.product_uom_qty > 0
                    for line in order.order_line if not line.is_delivery):
                res = dict(res, price=0.0, carrier_price=0.0,
                           warning_message=res.get('warning_message') or False)
        except Exception:  # noqa: BLE001 — nunca romper el cálculo del envío
            _logger.exception("minorista: no pude aplicar el envío gratis por producto")
        return res
