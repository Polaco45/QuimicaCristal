# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Primer cálculo del orden de la escalera (caja y web) con lo aceptado hasta hoy.
    try:
        with cr.savepoint():
            env = api.Environment(cr, SUPERUSER_ID, {})
            _logger.info("venta guiada: escalera inicial %s", env['cristal.vg.event']._cron_update_ladder_order())
    except Exception:  # noqa: BLE001
        _logger.exception("venta guiada: no pude calcular el orden de la escalera al migrar")
