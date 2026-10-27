# -*- coding: utf-8 -*-
"""Migración 18.0.1.43.0 — Mejoras del 27/10/2026 ("hacé todas esas mejoras").

- Claves de API: quedan SOLO en ir.config_parameter; se borran de cristal.agent.config
  (que el conector MCP puede leer).
- Espera antes de contestar: 10 → 15 segundos (junta mejor la ráfaga).
- Números que WhatsApp rechaza en los últimos 120 días → "No contactar".
- Primer informe semanal (semana del 20 al 26/10) en el canal interno.
"""
import logging
from datetime import date

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

KEYS = {'anthropic_api_key': 'cristal_agent.anthropic_api_key',
        'openai_api_key': 'cristal_agent.openai_api_key'}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Param = env['ir.config_parameter'].sudo()
    for column, param in KEYS.items():
        cr.execute(f"SELECT {column} FROM cristal_agent_config "
                   f"WHERE {column} IS NOT NULL AND {column} != '' LIMIT 1")
        row = cr.fetchone()
        if row and row[0] and not Param.get_param(param):
            Param.set_param(param, row[0].strip())
        cr.execute(f"UPDATE cristal_agent_config SET {column} = NULL")
    _logger.info("✅ MIGRATION 1.43.0: claves de API solo en ir.config_parameter")

    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if config and (config.debounce_seconds or 0) < 15:
        config.debounce_seconds = 15

    Report = env['cristal.agent.weekly.report']
    try:
        marked = Report.cron_wa_failures(days=120)
        _logger.info("✅ MIGRATION 1.43.0: %s contactos a 'No contactar' por rechazos de "
                     "WhatsApp: %s", len(marked), [p.name for p, _r in marked])
    except Exception as e:
        _logger.warning("MIGRATION 1.43.0: no pude revisar rechazos de WhatsApp: %s", e)
    try:
        if not Report.search_count([]):
            rep = Report.build_report(date(2026, 10, 20), date(2026, 10, 27))
            rep._post_to_internal_channel()
    except Exception as e:
        _logger.warning("MIGRATION 1.43.0: no pude armar el primer informe: %s", e)
