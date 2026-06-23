# -*- coding: utf-8 -*-
"""
Migración 18.0.1.12.0 — Cotización SIEMPRE sobre oportunidad + Combo Emprendedor.

- `create_sale_order` ahora vincula/crea la oportunidad del cliente y avanza la
  fase (la cotización ya no queda "en el aire").
- Nuevo Combo Emprendedor (combo fijo configurable) que el bot ofrece a los que
  arrancan. prompt_builder lo inyecta al contexto.
- Recarga el prompt v4 (con el puntero al combo).
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        _logger.warning("MIGRATION 1.12.0: no hay config activa")
        return

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v4.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v4'})
        _logger.info("✅ MIGRATION 1.12.0: prompt v4 recargado (%s chars)", len(content))

    # Default del nombre del combo (si quedó vacío tras crear la columna)
    if not config.combo_emprendedor_name:
        config.combo_emprendedor_name = 'Combo Emprendedor'
