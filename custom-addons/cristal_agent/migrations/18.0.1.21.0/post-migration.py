# -*- coding: utf-8 -*-
"""
Migración 18.0.1.21.0 — Fortalecer a Claudio (máquina de vender proactiva).

Recarga el prompt v4 (con las nuevas reglas: cotización única, mínimo 20L granel
sin excepción, mínimo de compra $50k / piso $39.990 + upsell, precisión de
producto, autonomía total y nada de actividades a Joaco).

Cambios de código que acompañan (no requieren migración de datos):
- create_sale_order: cotización única (reusa borrador), mínimos, stock.
- cron_cadence_quoted: cancela a los +7 días con mensaje de reenganche.
- schedule_activity: actividades siempre al bot, nunca a Joaco.
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        _logger.warning("MIGRATION 1.21.0: no hay config activa")
        return

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v4.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v4'})
        _logger.info("✅ MIGRATION 1.21.0: prompt v4 recargado (%s chars)", len(content))
