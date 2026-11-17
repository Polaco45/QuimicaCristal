# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # 17/11/2026 (Joaco): la promo de cloro 6 kg (11954) y la promo completa (12215) van con
    # envío gratis. Se guarda en un parámetro para poder sumar o sacar productos sin deploy.
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ir.config_parameter'].set_param('cristal_minorista.envio_gratis_productos', '11954,12215')
    _logger.info("cristal_minorista 1.7.0: envío gratis para productos 11954,12215")
