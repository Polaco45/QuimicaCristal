# -*- coding: utf-8 -*-
"""
Migración 18.0.1.31.1 — Recarga el prompt v5 con el target mayorista afinado:
comercio propio (despensa/kiosco/almacén…) = revende = MAYORISTA; ante la duda
es mayorista + mandar la lista; etiquetar al primer indicio.
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
        'data', 'prompts', 'claudio_v5.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v5'})
        _logger.info("✅ MIGRATION 1.31.1: prompt v5 recargado (target mayorista afinado, %s chars)",
                     len(content))
    else:
        _logger.warning("⚠️ MIGRATION 1.31.1: no se encontró claudio_v5.md")
