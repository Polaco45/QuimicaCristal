# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.3.0:
- Actualiza el system prompt a Claudio v3 (proceso comercial reformulado)
- Desactiva entries de KB que mencionen CRILIMP
- Mantiene las identidades técnicas configuradas

Se corre automáticamente cuando se hace upgrade del módulo.
"""
import os
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1. Cargar el prompt v3
    try:
        # __file__ acá es .../migrations/18.0.1.3.0/post-migration.py
        # módulo está 2 niveles arriba
        migration_path = os.path.dirname(os.path.realpath(__file__))
        module_path = os.path.dirname(os.path.dirname(migration_path))
        prompt_path = os.path.join(module_path, 'data', 'prompts', 'claudio_v3.md')

        if os.path.exists(prompt_path):
            with open(prompt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            config = env['cristal.agent.config'].sudo().search(
                [('active', '=', True)], limit=1
            )
            if config:
                config.write({
                    'system_prompt': content,
                    'prompt_version': 'claudio_v3',
                })
                _logger.info(
                    "✅ MIGRATION 1.3.0: prompt actualizado a Claudio v3 (%s chars)",
                    len(content)
                )
        else:
            _logger.warning("MIGRATION 1.3.0: no se encontró claudio_v3.md")
    except Exception as e:
        _logger.exception("MIGRATION 1.3.0: error cargando prompt: %s", e)

    # 2. Desactivar entries de KB que mencionen CRILIMP
    try:
        Knowledge = env['cristal.agent.knowledge'].sudo()
        crilimp_entries = Knowledge.search([
            '|', ('content', 'ilike', 'CRILIMP'),
            ('content', 'ilike', 'crilimp'),
            ('active', '=', True),
        ])
        if crilimp_entries:
            crilimp_entries.write({'active': False})
            _logger.info(
                "✅ MIGRATION 1.3.0: desactivadas %s entries de KB con CRILIMP",
                len(crilimp_entries)
            )
    except Exception as e:
        _logger.exception("MIGRATION 1.3.0: error limpiando KB: %s", e)

    # 3. Actualizar la entry de calificación con el texto correcto (sin CRILIMP)
    try:
        kb_qual = env.ref('cristal_agent.kb_mayorista_qualification', raise_if_not_found=False)
        if kb_qual:
            kb_qual.sudo().write({
                'content': "Para que un mayorista califique necesita: (a) facturar al menos $50.000/mes "
                           "en productos de limpieza, Y (b) estar en zona de cobertura: Río Cuarto + "
                           "200km a la redonda. Si NO califica → escalá a Joaco para que él decida "
                           "cómo manejarlo.",
                'active': True,
            })
            _logger.info("✅ MIGRATION 1.3.0: entry kb_mayorista_qualification actualizada")
    except Exception as e:
        _logger.exception("MIGRATION 1.3.0: error actualizando kb_mayorista_qualification: %s", e)
