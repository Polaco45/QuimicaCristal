# -*- coding: utf-8 -*-
"""Migración 18.0.1.31.10 — Takeover más largo (12h) + prompt: el bot no
coordina la entrega ni se mete cuando un humano está atendiendo."""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        return

    # Takeover por intervención manual: 1h → 12h (que no vuelva a interrumpir).
    try:
        if not config.human_takeover_hours or config.human_takeover_hours < 2:
            config.human_takeover_hours = 12
            _logger.info("✅ MIGRATION 1.31.10: human_takeover_hours = 12")
    except Exception as e:
        _logger.warning("MIGRATION 1.31.10: no pude setear human_takeover_hours: %s", e)

    # Recargar prompt v5 (regla de entrega / no meterse con el humano).
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v5.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v5'})
        _logger.info("✅ MIGRATION 1.31.10: prompt v5 recargado (entrega/takeover, %s chars)",
                     len(content))
    else:
        _logger.warning("⚠️ MIGRATION 1.31.10: no se encontró claudio_v5.md")
