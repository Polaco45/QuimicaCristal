# -*- coding: utf-8 -*-
"""Migración 18.0.1.42.0 — Bajar el costo por respuesta de ~US$ 0,13 a ~US$ 0,01.

Joaco (27/10/2026): "hacé las modificaciones pertinentes para bajar hasta ahí, sin
perder funcionalidades y mejorando la autonomía de Haiku". Medido del 20 al 27/10:
Sonnet 5.5 a US$ 0,13 por respuesta, ~90 % del costo en escribir la conversación de
cada cliente en la caché de 1 hora.

- Modelo base: Claude Haiku 5.5. Avanzado (reclamos, fotos/PDF, pedidos largos,
  institucionales, comandos de Joaco o cuando Haiku lo pide): Claude Sonnet 5.5.
- Tope de gasto diario: US$ 2 (después, solo Haiku y aviso en el canal interno).
- Prompt v7 recargado (contexto ya cargado, ask_advanced_model, mark_opt_out).
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        return
    vals = {'anthropic_model': 'claude-haiku-5-5',
            'anthropic_model_complex': 'claude-sonnet-5-5',
            'daily_budget_usd': 2.0,
            'escalate_client_msgs_to_strong': False}
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v7.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            vals.update({'system_prompt': f.read(), 'prompt_version': 'claudio_v7'})
    config.write(vals)
    _logger.info("✅ MIGRATION 1.42.0: Haiku 5.5 base, Sonnet 5.5 avanzado, tope US$ 2/día, "
                 "prompt v7 recargado")
