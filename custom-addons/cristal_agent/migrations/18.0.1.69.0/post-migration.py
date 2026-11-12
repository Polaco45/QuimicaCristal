# -*- coding: utf-8 -*-
"""Migración 18.0.1.69.0 — Menos pases a Joaco (auditoría de conversión 12/11/2026).

Fuera de zona y excepciones de mínimo o flete se resuelven con reglas fijas, sin escalar.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

REPLACEMENTS = [
    ("a su cargo.\"* y escalá a Joaco **una vez**.",
     "a su cargo.\"* **No lo escales**: anotá la localidad con `update_observation`. Recién si pide envío a su localidad o el pedido supera los .000, escalá a Joaco una vez."),
    ("No inventes excepciones ni descuentos de flete.",
     "No inventes excepciones ni descuentos de flete. **Si pide una excepción al mínimo o al flete, no escales**: explicá la regla en una línea y ofrecé sumar productos para llegar (con su precio) o retirar en planta sin mínimo."),
    ("localidad **fuera de circuito**,",
     "localidad **fuera de circuito** solo si pide envío o supera .000 (si no, retiro o transporte propio, sin escalar),"),
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
            _logger.warning("⚠️ MIGRATION 1.69.0: no encontré en el prompt: %s…", old[:60])
    if text != config.system_prompt:
        config.system_prompt = text
        _logger.info("✅ MIGRATION 1.69.0: prompt actualizado (menos pases a Joaco)")
