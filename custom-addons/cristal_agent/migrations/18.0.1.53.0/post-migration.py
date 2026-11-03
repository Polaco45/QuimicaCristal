# -*- coding: utf-8 -*-
"""Migración 18.0.1.53.0 — Claudio confirma pedidos mayoristas, productos a pedido,
variantes y búsqueda de productos (03/11/2026, caso Florencia S06925 y "bases desod").

- Prompt v9: confirm_order, a pedido vs stock, variantes, desodorante de pisos, marcas.
- Confirmación automática: prendida, hasta $150.000 sin IVA (propuesta del plan que Joaco
  aprobó con "avanza con todo esto").
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        'data', 'prompts', 'claudio_v9.md')
    if config and os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            config.write({'system_prompt': f.read(), 'prompt_version': 'claudio_v9'})
        _logger.info("✅ MIGRATION 1.53.0: prompt v9 cargado")
    if config:
        config.write({'auto_confirm_enabled': True,
                      'auto_confirm_max_amount': config.auto_confirm_max_amount or 150000.0})
