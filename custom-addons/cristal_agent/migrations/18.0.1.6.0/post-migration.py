# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.6.0:
- Recarga el prompt Claudio v3.1 (agregado R10 sobre templates de WhatsApp y
  ventana 24hs)
- Las cadencias default vienen del XML (data/default_cadences.xml)
- El modelo cristal.agent.cadence se crea automáticamente al cargar el módulo
"""
import os
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    _reload_prompt(env)
    _log_summary(env)


def _reload_prompt(env):
    try:
        migration_path = os.path.dirname(os.path.realpath(__file__))
        module_path = os.path.dirname(os.path.dirname(migration_path))
        prompt_path = os.path.join(module_path, 'data', 'prompts', 'claudio_v3_1.md')
        if not os.path.exists(prompt_path):
            _logger.warning("MIGRATION 1.6.0: claudio_v3_1.md no encontrado")
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
                "✅ MIGRATION 1.6.0: prompt v3.1 recargado (%s chars)",
                len(content)
            )
    except Exception as e:
        _logger.exception("MIGRATION 1.6.0 [prompt]: %s", e)


def _log_summary(env):
    try:
        cadences = env['cristal.agent.cadence'].sudo().search([('active', '=', True)])
        templates = env['whatsapp.template'].sudo().search([])
        cadences_with_template = cadences.filtered(lambda c: c.whatsapp_template_id)
        _logger.info(
            "MIGRATION 1.6.0 SUMMARY: "
            "%s cadencias activas, %s con template asignado, %s templates WA disponibles",
            len(cadences), len(cadences_with_template), len(templates)
        )
        if not cadences_with_template:
            _logger.warning(
                "⚠️  IMPORTANTE: Ninguna cadencia tiene template asignado todavía. "
                "Andá a 🤖 Cristal Agent → Conocimiento → 📅 Cadencias proactivas "
                "y asignale el template de WhatsApp correspondiente a cada paso."
            )
    except Exception as e:
        _logger.exception("MIGRATION 1.6.0 [summary]: %s", e)
