# -*- coding: utf-8 -*-
"""Migración 18.0.1.48.0 — Claudio confirma solo los pedidos de consumidor final.

Joaco (28/10/2026): "que confirme solo y solo pago transferencia y efectivo". Prompt v7
recargado con confirm_cf_order (sección 4b y reglas de oro 2 y 5).
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v7.md')
    if config and os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            config.write({'system_prompt': f.read(), 'prompt_version': 'claudio_v7'})
        _logger.info("✅ MIGRATION 1.48.0: prompt v7 recargado (confirm_cf_order)")
