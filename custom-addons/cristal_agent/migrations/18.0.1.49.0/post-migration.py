# -*- coding: utf-8 -*-
"""Migración 18.0.1.49.0 — Envío gratis de consumidor final desde $49.000.

Joaco (29/10/2026): "49k". Prompt v7
recargado con el monto nuevo; create_sale_order lo lee del método de envío.
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
        _logger.info("✅ MIGRATION 1.49.0: prompt v7 recargado (envío gratis $49.000)")
