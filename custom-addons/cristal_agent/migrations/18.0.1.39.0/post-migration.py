# -*- coding: utf-8 -*-
"""Migración 18.0.1.39.0 — Con la ventana de 24 h cerrada, el mensaje sale por plantilla.

Joaco (21/10/2026): "está queriendo hacer los seguimientos a ventanas cerradas y no con
la plantilla". send_whatsapp ahora manda solo por la plantilla genérica aprobada de la
cuenta. Se recarga el prompt v7 (regla de la ventana) y se actualiza la KB 30.
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

KB_LINE = ("- DESDE 21/10/2026: no hace falta mandar la plantilla a mano. Con la ventana "
           "de 24 h cerrada, send_whatsapp manda el mensaje solo por la plantilla aprobada "
           "('Hola <nombre>. Como estas? <texto>'). Nunca escales a Joaco porque la "
           "ventana esté cerrada.")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    kb = env['cristal.agent.knowledge'].sudo().with_context(active_test=False).browse(30)
    if kb.exists() and KB_LINE not in (kb.content or ''):
        kb.content = (kb.content or '').rstrip() + "\n" + KB_LINE
        _logger.info("✅ MIGRATION 1.39.0: KB #30 — la ventana cerrada sale por plantilla")

    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v7.md')
    if config and os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v7'})
        _logger.info("✅ MIGRATION 1.39.0: prompt v7 recargado (%s chars)", len(content))
