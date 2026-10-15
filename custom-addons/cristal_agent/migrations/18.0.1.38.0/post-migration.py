# -*- coding: utf-8 -*-
"""Migración 18.0.1.38.0 — Retiro en planta SIN compra mínima.

Joaco (15/10/2026): "está contando la compra mínima para el local también, cuando en
el local pueden ir a buscar tranquilamente sin mínimo". Caso real: Valeria di
Giovanni quiso mandar a buscar 1 bidón de Skip y Claudio se lo negó por el mínimo.

La compra mínima ($50.000 Río Cuarto / mínimo de la ruta) es SOLO para envíos. Se
corrigen las KB que decían que aplica siempre y se recarga el prompt v7.
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

PICKUP_RULE = ("RETIRO EN PLANTA SIN COMPRA MÍNIMA: el cliente que retira en San Martín "
               "2350 puede llevar lo que necesite (un solo bidón también), sin flete. La "
               "compra mínima es SOLO para envíos.")

REPLACEMENTS = {
    19: [("- Para todos los clientes mayoristas, SÍ aplica el mínimo de compra de $50.000 "
          "por pedido (independientemente del tipo de producto).",
          "- Con ENVÍO aplica la compra mínima ($50.000 en Río Cuarto; el mínimo de la "
          "ruta en los pueblos). Si el cliente RETIRA en la planta NO hay compra mínima.")],
    59: [("- La compra mínima de siempre aplica igual: $50.000 + 20 L granel mínimo.",
          "- Con envío aplica la compra mínima de siempre ($50.000 en Río Cuarto); si "
          "retira en la planta no hay compra mínima. El granel va siempre en bidones de "
          "20 L.")],
}
APPEND = {
    89: "- " + PICKUP_RULE,
    102: ("- RETIRO EN PLANTA: un cliente de pueblo que prefiere retirar en Río Cuarto no "
          "tiene mínimo ni flete."),
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Knowledge = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    for kb_id, pairs in REPLACEMENTS.items():
        kb = Knowledge.browse(kb_id)
        if not kb.exists():
            continue
        content = kb.content or ''
        for old, new in pairs:
            if old in content:
                content = content.replace(old, new)
                _logger.info("✅ MIGRATION 1.38.0: KB #%s — mínimo solo con envío", kb_id)
            elif 'RETIRA en la planta' not in content and 'retira en la planta' not in content:
                content = content.rstrip() + "\n" + new
                _logger.warning("⚠️ MIGRATION 1.38.0: KB #%s — no encontré el texto viejo; "
                                "agregué la regla al final", kb_id)
        kb.content = content
    for kb_id, line in APPEND.items():
        kb = Knowledge.browse(kb_id)
        if kb.exists() and line not in (kb.content or ''):
            kb.content = (kb.content or '').rstrip() + "\n" + line
            _logger.info("✅ MIGRATION 1.38.0: KB #%s — agregada la regla de retiro", kb_id)

    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v7.md')
    if config and os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v7'})
        _logger.info("✅ MIGRATION 1.38.0: prompt v7 recargado (%s chars)", len(content))
