# -*- coding: utf-8 -*-
"""
Migración 18.0.1.9.6 — Fix institucional: opportunities (no leads), email, coordinar visita.

Cambios:
- complete_institutional_qualification ahora crea OPORTUNIDAD (no lead) y reusa existente
- Resuelve rubro_partner_category_id por nombre si viene 0
- En cualquier error del cierre, SIEMPRE activa human_takeover (anti-huérfanos)
- Actividad cambia de "Visitar Institucion +1d" a "Llamada/Coordinar visita HOY"
- Email es ahora OBLIGATORIO en la calificación (7 preguntas)
- create_lead.py: type='opportunity' siempre
- send_whatsapp_template.py: no crea más leads [Auto], reusa opp del partner

Re-carga el prompt institucional desde el .md actualizado.
"""
import logging
import os
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("⚙️  MIGRATION 1.9.6: fixes institucional (opportunities, email, coordinar visita)")

    # Recargar prompt institucional desde el archivo (con la tabla de rubros + email)
    cr.execute("""
        SELECT id FROM cristal_agent_config WHERE active=true LIMIT 1
    """)
    row = cr.fetchone()
    if not row:
        _logger.warning("No hay config activa, salteo recarga de prompt")
        return

    config_id = row[0]
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_institutional_v1.md'
    )
    if not os.path.exists(prompt_path):
        _logger.warning("Archivo de prompt no encontrado: %s", prompt_path)
        return

    with open(prompt_path, 'r', encoding='utf-8') as f:
        prompt_content = f.read()

    cr.execute("""
        UPDATE cristal_agent_config
        SET system_prompt_institutional = %s
        WHERE id = %s
    """, (prompt_content, config_id))
    _logger.info("✅ Prompt institucional recargado: %d chars", len(prompt_content))
