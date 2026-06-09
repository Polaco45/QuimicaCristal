# -*- coding: utf-8 -*-
"""
Migración 18.0.1.10.5 — Fixes de cierre/ventana + optimización de costos.

- Fix cierre atómico (AccessError): rebind a superusuario en los dispatchers.
- Fix falso WINDOW_CLOSED en respuestas a inbound.
- Fix mensaje de cierre que se mandaba con ok=False → endurecido en el prompt
  institucional (cierre SOLO si ok=true; si no, escalate_to_joaco + pause_bot).
- Optimización de costos: cache 1h beta, prefijo cacheado estable (timestamp
  fuera del bloque cacheado), prompt institucional achicado, trim de historial.

Esta migración recarga el prompt institucional v2 (achicado + cierre endurecido)
en la config activa.
"""
import logging
import os

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("⚙️  MIGRATION 1.10.5: recarga prompt institucional (achicado + cierre endurecido)")
    cr.execute("SELECT id FROM cristal_agent_config WHERE active=true LIMIT 1")
    row = cr.fetchone()
    if not row:
        _logger.warning("MIGRATION 1.10.5: no hay config activa, salteo recarga de prompt")
        return
    config_id = row[0]
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_institutional_v2.md'
    )
    if not os.path.exists(prompt_path):
        _logger.warning("MIGRATION 1.10.5: no se encontró claudio_institutional_v2.md")
        return
    with open(prompt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    cr.execute(
        "UPDATE cristal_agent_config SET system_prompt_institutional = %s WHERE id = %s",
        (content, config_id),
    )
    _logger.info(
        "✅ Prompt institucional v2.1 recargado (%s chars, cierre solo si ok=true)",
        len(content),
    )
