# -*- coding: utf-8 -*-
"""
Migración 18.0.1.9.7 — Empresa madre SIEMPRE en flow institucional.

Cambios:
- complete_institutional_qualification: incluso cuando necesita_factura=False,
  ahora SE CREA la empresa como res.partner is_company=True (sin CUIT) y el
  contacto queda como subcontacto. Antes solo se creaba con factura.
- company_name pasa a ser OBLIGATORIO en qualification_data
- Prompt institucional refuerza: el bot DEBE pedir el nombre de la empresa
  aunque el cliente solo dé su nombre personal
- Las categorías EMPRESA + Rubro van en la empresa madre, NUNCA en el contacto

Re-carga el prompt institucional.
"""
import logging
import os
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("⚙️  MIGRATION 1.9.7: empresa madre SIEMPRE (sin factura tambien)")

    cr.execute("SELECT id FROM cristal_agent_config WHERE active=true LIMIT 1")
    row = cr.fetchone()
    if not row:
        return

    config_id = row[0]
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_institutional_v1.md'
    )
    if not os.path.exists(prompt_path):
        return

    with open(prompt_path, 'r', encoding='utf-8') as f:
        prompt_content = f.read()

    cr.execute("""
        UPDATE cristal_agent_config
        SET system_prompt_institutional = %s
        WHERE id = %s
    """, (prompt_content, config_id))
    _logger.info("✅ Prompt institucional v1.9.7 recargado: %d chars", len(prompt_content))
