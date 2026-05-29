# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.7.0:
- Recarga prompt v3.1 con calificación en LITROS (no en facturación)
- Los campos boolean nuevos de feature flags se crean automáticamente con
  default=True (excepto level_recalculation y churn_detection que son False)
- Los campos numéricos de rangos por defecto: 500 BRONCE max, 1500 PLATA max
"""
import os
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Recargar prompt
    try:
        migration_path = os.path.dirname(os.path.realpath(__file__))
        module_path = os.path.dirname(os.path.dirname(migration_path))
        prompt_path = os.path.join(module_path, 'data', 'prompts', 'claudio_v3_1.md')
        if os.path.exists(prompt_path):
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
                    "✅ MIGRATION 1.7.0: prompt recargado con calificación en litros"
                )
    except Exception as e:
        _logger.exception("MIGRATION 1.7.0 [prompt]: %s", e)

    # Verificar que los rangos de litros tengan valores razonables
    try:
        config = env['cristal.agent.config'].sudo().search(
            [('active', '=', True)], limit=1
        )
        if config:
            updates = {}
            if not config.level_bronce_max_liters:
                updates['level_bronce_max_liters'] = 500
            if not config.level_plata_max_liters:
                updates['level_plata_max_liters'] = 1500
            if updates:
                config.write(updates)
                _logger.info(
                    "✅ MIGRATION 1.7.0: rangos de litros inicializados: %s",
                    updates
                )
    except Exception as e:
        _logger.exception("MIGRATION 1.7.0 [rangos]: %s", e)
