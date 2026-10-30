# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # El escalón de tamaño pasa a ofrecer el tamaño SIGUIENTE (1 L → 5 L), no el más grande:
    # se recalculan las sugerencias para que caja y web lo tomen ya.
    try:
        with cr.savepoint():
            env = api.Environment(cr, SUPERUSER_ID, {})
            env['cristal.vg.suggestion']._cron_recompute()
    except Exception:  # noqa: BLE001
        _logger.exception("venta guiada: no pude recalcular las sugerencias al migrar")
