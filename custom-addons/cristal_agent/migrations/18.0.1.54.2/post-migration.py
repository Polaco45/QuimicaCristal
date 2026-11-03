# -*- coding: utf-8 -*-
"""Migración 18.0.1.54.2 — El cierre de preventa pasa al MIÉRCOLES 18 h (día anterior al jueves).

Joaco, 03/11/2026: "Miércoles 18 h". Idempotente: en prod ya se aplicó por RPC el mismo día.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

KB_ROUTE_ID = 102
KB_REPLACEMENTS = [
    ("la preventa cierra el MARTES previo a las 18 h", "la preventa cierra el MIÉRCOLES previo a las 18 h"),
    ("la preventa cierra el martes 18 h previo al jueves", "la preventa cierra el miércoles 18 h previo al jueves"),
]
TEMPLATE_252 = ("hasta el martes {{4}} a las 18 h", "hasta el miércoles {{4}} a las 18 h")
PROMPT_OLD = "(el martes 18 h es preventa; el miércoles 12 h es rescate: no los mezcles)"
PROMPT_NEW = ("(la preventa cierra el día y hora que te da get_route_info, el miércoles 18 h; "
              "el rescate cierra el miércoles 12 h: no los mezcles)")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if config and config.route_preventa_cutoff_weekday != 2:
        config.route_preventa_cutoff_weekday = 2
        _logger.info("✅ MIGRATION 1.54.2: cierre de preventa → miércoles (2)")
    kb = env['cristal.agent.knowledge'].sudo().with_context(active_test=False).browse(KB_ROUTE_ID)
    if kb.exists():
        content = kb.content or ''
        for old, new in KB_REPLACEMENTS:
            content = content.replace(old, new)
        if content != kb.content:
            kb.content = content
            _logger.info("✅ MIGRATION 1.54.2: KB #%s cierre miércoles", KB_ROUTE_ID)
    tpl = env['whatsapp.template'].sudo().search([('template_name', '=', 'ruta_aviso_paso')], limit=1)
    if tpl and TEMPLATE_252[0] in (tpl.body or ''):
        tpl.body = tpl.body.replace(*TEMPLATE_252)
        _logger.info("✅ MIGRATION 1.54.2: plantilla ruta_aviso_paso cierre miércoles")
    if config and PROMPT_OLD in (config.system_prompt or ''):
        config.system_prompt = config.system_prompt.replace(PROMPT_OLD, PROMPT_NEW)
        _logger.info("✅ MIGRATION 1.54.2: prompt con cierre miércoles")
