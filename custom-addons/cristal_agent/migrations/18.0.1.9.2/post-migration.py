# -*- coding: utf-8 -*-
"""
Migración 18.0.1.9.2 — Hotfix:

1. Bug en complete_institutional_qualification.py:
   El validador de l10n_ar rechazaba CUITs con guiones o espacios porque el
   partner se creaba sin l10n_latam_identification_type_id seteado → quedaba
   como DNI (default) y DNI solo acepta números puros.
   Fix: sanitizar VAT a solo dígitos + setear identification_type_id = 4 (CUIT)
   al crear la empresa.

2. Bug en __init__.py:
   El post_init_load_prompt solo corre en INSTALACIÓN, no en UPGRADE. Al
   actualizar de 1.8.6 → 1.9.x el system_prompt_institutional quedaba vacío.
   Fix: este migrate() carga el prompt institucional desde el archivo .md
   si el campo está vacío (idempotente).
"""
import logging
import os
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Cargar prompt institucional si está vacío
    cr.execute("SELECT id, system_prompt_institutional FROM cristal_agent_config WHERE active = TRUE LIMIT 1")
    row = cr.fetchone()
    if not row:
        _logger.warning("MIGRATION 1.9.2: no hay config activo, skip carga de prompt")
        return

    config_id, current_prompt = row
    if current_prompt and len(current_prompt) > 100:
        _logger.info("MIGRATION 1.9.2: prompt institucional ya tenía contenido (%d chars), no se pisa", len(current_prompt))
        return

    # Buscar el archivo del prompt
    module_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    prompt_path = os.path.join(module_path, 'data', 'prompts', 'claudio_institutional_v1.md')

    if not os.path.exists(prompt_path):
        _logger.warning("MIGRATION 1.9.2: no existe %s", prompt_path)
        return

    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        cr.execute(
            "UPDATE cristal_agent_config SET system_prompt_institutional = %s WHERE id = %s",
            (content, config_id)
        )
        _logger.info(
            "✅ MIGRATION 1.9.2: prompt institucional cargado (%d chars) en config id=%s",
            len(content), config_id
        )
    except Exception as e:
        _logger.exception("Error cargando prompt institucional en migrate(): %s", e)
