# -*- coding: utf-8 -*-
"""Migración 18.0.1.67.0 — Decisiones de Joaco del 12/11/2026.

- Las cotizaciones se cancelan a los 14 días (antes 7, el cron de cadencia).
- Claudio confirma todos los pedidos hasta $200.000, también los de la ruta del camión.
- Lo que no puede confirmar se lo pide a Joaco por WhatsApp; Joaco responde "OK S0xxxx".
Reemplazos textuales e idempotentes sobre el prompt vivo.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

REPLACEMENTS = [
    ("Joaco confirma solo los que la tool no deja: ruta del camión, montos grandes, facturas vencidas, fuera de zona.",
     "Confirmás también los de la **ruta del camión**. Joaco confirma solo los que la tool no deja (más de .000, facturas vencidas, fuera de zona, sin stock): escalá con \"PEDIDO PARA CONFIRMAR\" y el sistema se lo pide a Joaco **por WhatsApp**; cuando responde, el pedido se confirma solo y el cliente recibe el aviso."),
    ("Si no se puede (ruta del camión, monto grande, facturas vencidas, fuera de zona), escalá:",
     "Si no se puede (más de .000, facturas vencidas, fuera de zona), escalá (le llega a Joaco por WhatsApp):"),
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config or not config.system_prompt:
        return
    text = config.system_prompt
    for old, new in REPLACEMENTS:
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new)
        else:
            _logger.warning("⚠️ MIGRATION 1.67.0: no encontré en el prompt: %s…", old[:60])
    if text != config.system_prompt:
        config.system_prompt = text
        _logger.info("✅ MIGRATION 1.67.0: prompt actualizado (ruta, confirmación por WhatsApp)")
