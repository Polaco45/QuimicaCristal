# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Sugerencias limpias (Joaco, 04/11/2026: "muy random"): se recalculan ya, sin esperar
    # al cron nocturno, con las reglas nuevas (sin relleno por rubro, sin sustitutos, mismo aroma).
    try:
        with cr.savepoint():
            env = api.Environment(cr, SUPERUSER_ID, {})
            Sugg = env['cristal.vg.suggestion']
            before = Sugg.search_count([('manual', '=', False)])
            Sugg._cron_recompute()
            after = Sugg.search_count([('manual', '=', False)])
            _logger.info("venta guiada 1.10.0: sugerencias automáticas %s → %s", before, after)
    except Exception:  # noqa: BLE001
        _logger.exception("venta guiada 1.10.0: no pude recalcular las sugerencias al migrar")
