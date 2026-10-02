# -*- coding: utf-8 -*-
"""Migración 18.0.1.34.0 — Precios correctos: recarga el prompt v7 (regla 6
reforzada: cada precio del producto exacto; el sistema bloquea precios por litro que
no salieron de las herramientas)."""
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
        'data', 'prompts', 'claudio_v7.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v7'})
        _logger.info("✅ MIGRATION 1.34.0: prompt v7 recargado (%s chars)", len(content))
