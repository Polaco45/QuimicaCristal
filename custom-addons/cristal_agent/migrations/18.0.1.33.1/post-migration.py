# -*- coding: utf-8 -*-
"""Migración 18.0.1.33.1 — Bidones: el recambio es un CANJE, no "traerlos".

Joaco: con envío, el cliente recibe los bidones con producto y en ese momento
entrega sus bidones vacíos con tapa; si retira, los lleva a la planta. Si no tiene
vacíos para canjear, cada bidón nuevo sale $3.500. Se recarga el prompt v7 y se
corrige el texto de bidones en la KB (#89 planta, #102 ruta, #16 formatos granel).
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

RECAMBIO = ("RECAMBIO DE BIDONES: el granel va en bidones de 20 L; por cada bidón lleno "
            "el cliente entrega un bidón vacío de 20 L con tapa. Si se lo enviamos, los "
            "vacíos los entrega en el momento de la entrega (no tiene que traer nada); si "
            "retira en planta, los lleva al retirar. Si no tiene vacíos para canjear, cada "
            "bidón nuevo sale $3.500. Decirlo SIEMPRE.")

REPLACEMENTS = {
    89: [
        ("El cliente trae sus bidones vacíos para el recambio (si no trae, cada bidón "
         "nuevo de 20 L sale $3.500) y el efectivo o el comprobante de la transferencia.",
         "El cliente lleva sus bidones vacíos de 20 L con tapa para el recambio (si no "
         "tiene, cada bidón nuevo sale $3.500) y el efectivo o el comprobante de la "
         "transferencia."),
    ],
    102: [
        ("- BIDONES: el granel va en bidones de 20 L; si el cliente no tiene vacíos para "
         "el recambio, cada bidón nuevo sale $3.500. Decirlo SIEMPRE.",
         "- " + RECAMBIO),
    ],
    16: [
        ("El cliente trae/devuelve sus propios bidones (canje de envases).", RECAMBIO),
    ],
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if config:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'data', 'prompts', 'claudio_v7.md')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            config.write({'system_prompt': content, 'prompt_version': 'claudio_v7'})
            _logger.info("✅ MIGRATION 1.33.1: prompt v7 recargado (%s chars)", len(content))

    Knowledge = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    for kb_id, pairs in REPLACEMENTS.items():
        kb = Knowledge.browse(kb_id)
        if not kb.exists():
            _logger.warning("⚠️ MIGRATION 1.33.1: KB #%s no existe", kb_id)
            continue
        content = kb.content or ''
        changed = False
        for old, new in pairs:
            if old in content:
                content = content.replace(old, new)
                changed = True
        if changed:
            kb.content = content
            _logger.info("✅ MIGRATION 1.33.1: KB #%s — texto de bidones corregido", kb_id)
        else:
            _logger.warning("⚠️ MIGRATION 1.33.1: KB #%s — no encontré el texto viejo "
                            "de bidones (revisar a mano)", kb_id)
