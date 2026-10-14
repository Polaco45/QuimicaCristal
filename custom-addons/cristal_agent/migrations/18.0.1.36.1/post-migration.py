# -*- coding: utf-8 -*-
"""Migración 18.0.1.36.1 — Claudio pasa de Claude Haiku 4.5 a Claude Sonnet 5.5.

Joaco (14/10/2026): "cambia el modelo, no quiero renegar más". Haiku 4.5 cumplía a
medias las reglas de un prompt largo (20%, bidones, días, zona, escalaciones).
Sonnet 5.5 razona antes de responder (esfuerzo medio), no usa temperature y
responde con otro modelo si se niega a algo. max_tokens sube a 16.000 porque el
razonamiento cuenta dentro de ese límite.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

NEW_MODEL = 'claude-sonnet-5-5'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for config in env['cristal.agent.config'].search([]):
        old = config.anthropic_model
        vals = {'anthropic_model': NEW_MODEL, 'anthropic_effort': 'medium'}
        if (config.max_tokens or 0) < 16000:
            vals['max_tokens'] = 16000
        config.write(vals)
        _logger.info("✅ MIGRATION 1.36.1: config %s — modelo %s → %s (esfuerzo medio, "
                     "max_tokens %s)", config.id, old, NEW_MODEL, config.max_tokens)
