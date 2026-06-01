# -*- coding: utf-8 -*-
"""
Migración 18.0.1.10.4 — Lead con contacto/empresa reales (no el perfil de WhatsApp).

create_lead ahora acepta contact_name y company_name y los graba en el lead
(contact_name / partner_name). Si el contacto es fresco (autocreado por WhatsApp,
sin email/empresa/padre), reemplaza su nombre por el real capturado en la charla,
en vez de dejar lo que trajo el perfil de WhatsApp (ej. "Química Cristal").

Recarga el prompt institucional v2 (STEP 2 ahora pasa contact_name/company_name).
"""
import logging
import os
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("⚙️  MIGRATION 1.10.4: lead con contacto/empresa reales")
    cr.execute("SELECT id FROM cristal_agent_config WHERE active=true LIMIT 1")
    row = cr.fetchone()
    if not row:
        return
    config_id = row[0]
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_institutional_v2.md'
    )
    if not os.path.exists(prompt_path):
        _logger.warning("MIGRATION 1.10.4: no se encontro claudio_institutional_v2.md")
        return
    with open(prompt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    cr.execute(
        "UPDATE cristal_agent_config SET system_prompt_institutional = %s WHERE id = %s",
        (content, config_id),
    )
    _logger.info("✅ Prompt institucional v2 recargado (STEP 2 con contacto/empresa)")
