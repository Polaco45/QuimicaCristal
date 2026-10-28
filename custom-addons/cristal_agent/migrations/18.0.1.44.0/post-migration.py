# -*- coding: utf-8 -*-
"""Migración 18.0.1.44.0 — Permiso para avisos por WhatsApp.

Sistema minorista (28/10/2026): Claudio pregunta una vez, al cerrar una cotización, si
el cliente quiere avisos por WhatsApp (reposición y promos) y lo anota con
set_promo_consent. Prompt v7 recargado con esa regla.
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
        _logger.info("✅ MIGRATION 1.44.0: prompt v7 recargado (avisos por WhatsApp)")
