# -*- coding: utf-8 -*-
"""
Migración 18.0.1.10.3 — Triage del STEP 0 consciente del estado del hilo.

Fix: el bot clasificaba como "ruido" (silencio) una confirmación en medio de la
calificación (ej. "asi es" tras "¿en Río Cuarto?"), cortando el flujo.

Ahora el STEP 0 decide según el ESTADO DEL HILO que inyecta prompt_builder:
- HILO ACTIVO (el bot ya intervino / hay datos de calificación) → el mensaje es
  continuación/respuesta → seguí el flujo. Nunca ruido.
- MENSAJE FRÍO (sin intervención previa) → lead claro: corre el flujo; no-lead
  (operativo/social/ruido): escala a Joaco + pause_bot(0).

Recarga el prompt institucional v2 (editado) en la config.
"""
import logging
import os
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("⚙️  MIGRATION 1.10.3: STEP 0 triage consciente del hilo")

    cr.execute("SELECT id FROM cristal_agent_config WHERE active=true LIMIT 1")
    row = cr.fetchone()
    if not row:
        _logger.warning("No hay config activa, salteo recarga de prompt institucional")
        return

    config_id = row[0]
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_institutional_v2.md'
    )
    if not os.path.exists(prompt_path):
        _logger.warning("MIGRATION 1.10.3: no se encontro claudio_institutional_v2.md")
        return

    with open(prompt_path, 'r', encoding='utf-8') as f:
        prompt_content = f.read()

    cr.execute(
        "UPDATE cristal_agent_config SET system_prompt_institutional = %s WHERE id = %s",
        (prompt_content, config_id),
    )
    _logger.info("✅ Prompt institucional v2 recargado (triage por hilo): %d chars", len(prompt_content))
