# -*- coding: utf-8 -*-
"""Migración 18.0.1.46.0 — Claudio pide reseña en Google a los clientes conformes.

Pedido de Joaco (28/10/2026): "necesito más reseñas en google". Se recarga el prompt v7
con la regla de la reseña (link directo a "Escribir una opinión" de la ficha).
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
        _logger.info("✅ MIGRATION 1.46.0: prompt v7 recargado (reseña en Google)")
