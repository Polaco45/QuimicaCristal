# -*- coding: utf-8 -*-
"""Migración 18.0.1.45.0 — Claudio le vende al consumidor final.

Sistema minorista (28/10/2026, "seguí con todo el resto de etapas"): el consumidor final
de Río Cuarto ya no se deriva al local. Se cotiza con create_sale_order(consumidor_final=
true): lista L.C 1, sin mínimo, envío de la regla #73 ($6.500, gratis desde $65.000) o
retiro. Se apagan las KB que mandaban a derivarlo y se recarga el prompt v7 (sección 4b).
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

# 17 Uso personal → derivar · 22/24 No califica como mayorista · 26 CF: derivar sin escalar
CF_DERIVE_KB = [17, 22, 24, 26]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    kb = env['cristal.agent.knowledge'].browse(CF_DERIVE_KB).exists()
    kb.write({'active': False})
    _logger.info("✅ MIGRATION 1.45.0: KB de derivación de consumidor final apagadas: %s", kb.ids)
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v7.md')
    if config and os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            config.write({'system_prompt': f.read(), 'prompt_version': 'claudio_v7'})
        _logger.info("✅ MIGRATION 1.45.0: prompt v7 recargado (consumidor final)")
