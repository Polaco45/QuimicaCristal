# -*- coding: utf-8 -*-
"""
Migración 18.0.1.13.0 — Lector de notas de voz (transcripción de audio).

- Claude no acepta audio: las notas de voz de WhatsApp ahora se transcriben con
  OpenAI (gpt-4o-transcribe) y se procesan como texto. Nuevos campos en la config
  (enable_audio_transcription, openai_api_key, transcription_model/language).
- Recarga el prompt v4 (que ya no dice "no procesás audios" y explica el prefijo
  [nota de voz]).
- Defaults seguros: la transcripción queda APAGADA hasta que Joaco cargue la key.
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        _logger.warning("MIGRATION 1.13.0: no hay config activa")
        return

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v4.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v4'})
        _logger.info("✅ MIGRATION 1.13.0: prompt v4 recargado (%s chars)", len(content))

    # Defaults de transcripción (la columna se crea con default, pero por las dudas)
    if not config.transcription_model:
        config.transcription_model = 'gpt-4o-transcribe'
    if not config.transcription_language:
        config.transcription_language = 'es'
    _logger.info("✅ MIGRATION 1.13.0: transcripción de audio lista (apagada hasta cargar key)")
