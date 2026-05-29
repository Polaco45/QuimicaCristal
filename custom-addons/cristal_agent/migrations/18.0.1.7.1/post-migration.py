# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.7.1:
- Recarga prompt v3.1 con calificación en litros pero niveles en pesos.
"""
import os
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    try:
        migration_path = os.path.dirname(os.path.realpath(__file__))
        module_path = os.path.dirname(os.path.dirname(migration_path))
        prompt_path = os.path.join(module_path, 'data', 'prompts', 'claudio_v3_1.md')
        if not os.path.exists(prompt_path):
            return
        with open(prompt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        config = env['cristal.agent.config'].sudo().search(
            [('active', '=', True)], limit=1
        )
        if config:
            config.write({
                'system_prompt': content,
                'prompt_version': 'claudio_v3_1',
            })
            _logger.info(
                "✅ MIGRATION 1.7.1: prompt recargado — calificación en litros, niveles en pesos"
            )
    except Exception as e:
        _logger.exception("MIGRATION 1.7.1 [prompt]: %s", e)
