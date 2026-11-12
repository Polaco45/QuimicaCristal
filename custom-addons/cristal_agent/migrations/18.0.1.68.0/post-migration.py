# -*- coding: utf-8 -*-
"""Migración 18.0.1.68.0 — 3 combos de entrada (Joaco 12/11/2026: precios 60, 75 y 107 mil).

Claudio elige con preguntas Prueba, Arranque o Completo y lo cotiza con quote_entry_combo;
el Combo Emprendedor queda solo para quien lo pide por nombre o contesta "YO".
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

REPLACEMENTS = [
    ("**Combo Emprendedor (para los que arrancan):** si hay un combo activo, te aparece en el contexto como **\"🎁 COMBO EMPRENDEDOR\"**. Cuando el cliente está **arrancando y no sabe qué llevar**, ofrecele ese combo como punto de partida y cotizalo tal cual (con el 20% off **solo si es de Río Cuarto / Las Higueras**). **SIEMPRE detallá qué incluye el combo.**",
     "**Combos de entrada (para los que arrancan):** te aparecen en el contexto como **\"🎁 COMBOS DE ENTRADA\"** (Prueba .000, Arranque .000, Completo .000). Cuando el cliente está **arrancando o no sabe qué llevar**, hacé las preguntas del bloque (de a una), ofrecé **UNO** y cotizalo con `quote_entry_combo` (aplica solo el 20% de primera compra si corresponde). **SIEMPRE detallá qué incluye el combo** y cuánto ahorra contra comprarlo suelto. El Combo Emprendedor queda solo para quien lo pide por nombre o contesta \"YO\"."),
    ("(el Combo Emprendedor para almacén, kiosco o quien arranca a revender; o el combo de su rubro si figura en el contexto)",
     "(si arranca o no sabe qué llevar, el combo de entrada que le corresponda según el bloque COMBOS DE ENTRADA)"),
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
            _logger.warning("⚠️ MIGRATION 1.68.0: no encontré en el prompt: %s…", old[:60])
    if text != config.system_prompt:
        config.system_prompt = text
        _logger.info("✅ MIGRATION 1.68.0: prompt actualizado (combos de entrada)")
