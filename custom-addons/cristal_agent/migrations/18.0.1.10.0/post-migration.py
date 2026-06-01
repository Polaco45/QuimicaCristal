# -*- coding: utf-8 -*-
"""
Migración 18.0.1.10.0 — Flow institucional v2: triage de intención + orden nuevo.

Cambios:
- Nuevo prompt institucional (claudio_institutional_v2.md):
  * STEP 0 TRIAGE: clasifica cada mensaje entrante a la cuenta Compras en
    A) lead interesado → corre el flujo
    B) consulta operativa → línea de espera + escalate_to_joaco + pause_bot(0)
    C) ruido/social/equivocado → NO responde (silencio total)
  * Orden nuevo: nombre+empresa → create_lead (opp temprana, idempotente) →
    propuesta + reporte de muestra (adjunto) + CTA visita → si SÍ, calificación
    completa con chequeo de zona → complete_institutional_qualification.
- Campo nuevo institutional_report_attachment_id (PDF de muestra del reporte).
- prompt_builder inyecta el ID del reporte en el placeholder
  {{REPORTE_MUESTRA_ATTACHMENT_ID}}.

NO toca el ruteo institucional/mayorista ni el bypass de cliente activo (siguen igual).
"""
import logging
import os
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("⚙️  MIGRATION 1.10.0: flow institucional v2 (triage + orden nuevo)")

    cr.execute("SELECT id FROM cristal_agent_config WHERE active=true LIMIT 1")
    row = cr.fetchone()
    if not row:
        _logger.warning("No hay config activa, salteo recarga de prompt institucional v2")
        return

    config_id = row[0]
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_institutional_v2.md'
    )
    if not os.path.exists(prompt_path):
        _logger.warning("MIGRATION 1.10.0: no se encontró claudio_institutional_v2.md en %s", prompt_path)
        return

    with open(prompt_path, 'r', encoding='utf-8') as f:
        prompt_content = f.read()

    cr.execute(
        "UPDATE cristal_agent_config SET system_prompt_institutional = %s WHERE id = %s",
        (prompt_content, config_id),
    )
    _logger.info("✅ Prompt institucional v2 cargado: %d chars", len(prompt_content))

    # Recordatorio operativo: el adjunto del reporte queda sin setear; Joaco
    # lo carga desde la UI (Config → Institucional → Reporte de muestra).
    cr.execute(
        "SELECT institutional_report_attachment_id FROM cristal_agent_config WHERE id = %s",
        (config_id,),
    )
    att = cr.fetchone()
    if not att or not att[0]:
        _logger.warning(
            "⚠️ MIGRATION 1.10.0: institutional_report_attachment_id NO está seteado. "
            "El bot va a mandar la propuesta SIN adjunto hasta que se cargue el PDF "
            "del reporte en Config → Institucional."
        )
