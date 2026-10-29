# -*- coding: utf-8 -*-
"""Migración 18.0.1.49.2 — El envío a domicilio vuelve a ser gratis desde $65.000.

Joaco (29/10/2026): "cambio, el envío a domicilio es gratis a partir de 65000". Esa
mañana el de consumidor final (método 14, el de la web, que también usa la regla #73
para la lista L.C 1) había quedado en $49.000; el mayorista (método 1) ya estaba en
$65.000. Se iguala el 14 y se recarga el prompt v7.
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

FREE_FROM = 65000.0


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    carrier = env['delivery.carrier'].sudo().with_context(active_test=False).browse(14)
    if carrier.exists() and carrier.free_over and carrier.amount != FREE_FROM:
        old = carrier.amount
        carrier.amount = FREE_FROM
        _logger.info("✅ MIGRATION 1.49.2: método %s '%s' gratis desde %s (antes %s)",
                     carrier.id, carrier.name, FREE_FROM, old)

    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v7.md')
    if config and os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            config.write({'system_prompt': f.read(), 'prompt_version': 'claudio_v7'})
        _logger.info("✅ MIGRATION 1.49.2: prompt v7 recargado (envío gratis $65.000)")
