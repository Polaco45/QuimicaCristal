# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Bajar los opcionales/alternativos/accesorios nativos: la web usa nuestra escalera.
    try:
        with cr.savepoint():
            env = api.Environment(cr, SUPERUSER_ID, {})
            env['cristal.vg.suggestion']._cristal_sync_website()
    except Exception:  # noqa: BLE001
        _logger.exception("venta guiada: no pude actualizar la web al migrar")
