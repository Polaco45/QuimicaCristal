# -*- coding: utf-8 -*-
"""
Migración 18.0.1.26.0 — Recarga del prompt v4.

Recarga claudio_v4.md: checklist antes de confirmar (dirección + envases 20L /
$3.500), PDF siempre adjunto.
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        return
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v4.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v4'})
        _logger.info("✅ MIGRATION 1.26.0: prompt v4 recargado (%s chars)", len(content))
