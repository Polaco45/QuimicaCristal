# -*- coding: utf-8 -*-
"""Migración 18.0.1.41.0 — Horario nuevo de la planta (desde el 26/10/2026).

Joaco: "a partir de ahora van a ser de 8 a 13 y de 17 a 20 hs" (lunes a viernes; el
sábado sigue de 9 a 13). Se reemplaza el horario viejo en las KB que lo citan, sin
pisar el resto del texto (que se fue editando a mano).
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

KB_REPLACEMENTS = {
    89: [("lunes a viernes de 8:30 a 12:30 y de 15:30 a 19:30",
          "lunes a viernes de 8:00 a 13:00 y de 17:00 a 20:00")],
    70: [("Lun a Vie 8:30 a 19:30",
          "Lun a Vie 8:00 a 13:00 y 17:00 a 20:00")],
    26: [("Lunes a viernes: 8:30-12:30 y 15:30-19:30",
          "Lunes a viernes: 8:00-13:00 y 17:00-20:00")],
    81: [("lun-vie 8:30-19:30", "lun-vie 8:00-13:00 y 17:00-20:00")],
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Knowledge = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    for kb_id, pairs in KB_REPLACEMENTS.items():
        kb = Knowledge.browse(kb_id)
        if not kb.exists():
            _logger.warning("⚠️ MIGRATION 1.41.0: KB #%s no existe", kb_id)
            continue
        content = kb.content or ''
        for old, new in pairs:
            if old in content:
                content = content.replace(old, new)
            elif new not in content:
                _logger.warning("⚠️ MIGRATION 1.41.0: KB #%s — no encontré '%s' "
                                "(revisar a mano)", kb_id, old)
        if content != (kb.content or ''):
            kb.content = content
            _logger.info("✅ MIGRATION 1.41.0: KB #%s con el horario nuevo", kb_id)
