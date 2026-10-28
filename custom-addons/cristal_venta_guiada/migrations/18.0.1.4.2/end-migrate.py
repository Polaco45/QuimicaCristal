# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # La web con la escalera de la caja desde ya, sin esperar al recálculo nocturno.
    # Si falla, la actualización sigue: lo vuelve a intentar el cron de la noche.
    try:
        with cr.savepoint():
            api.Environment(cr, SUPERUSER_ID, {})['cristal.vg.suggestion']._cristal_sync_website()
    except Exception:  # noqa: BLE001
        _logger.exception("venta guiada: no pude actualizar la web al migrar")
