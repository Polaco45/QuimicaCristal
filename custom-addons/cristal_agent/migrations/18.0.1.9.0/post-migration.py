# -*- coding: utf-8 -*-
"""
Migración 18.0.1.9.0 — Flow institucional dual.

Cambios estructurales en este release:

1. cristal.agent.memory:
   - + client_type (selection mayorista/institucional/unknown, default unknown)
   - + qualification_data (JSON con datos transitorios)
   - flow_state extendido con 12 estados institucionales nuevos

2. cristal.agent.cadence:
   - + client_type (selection mayorista/institucional/both, default mayorista)

3. cristal.agent.config:
   - + system_prompt_institutional (opcional)
   - restricted_wa_account_ids ahora se espera con [5, 8] para dual operation

4. services/prompt_builder.py:
   - build_system_prompt acepta client_type y switchea entre prompts

5. models/whatsapp_message.py:
   - Detección de client_type en el pipeline (wa_account_id principal)
   - Bypass de calificación SOLO para institucional (mayorista nunca skip)

Este script de migración:
- Llena client_type='mayorista' en los memories EXISTENTES (todos vienen
  del flow Claudio v3.1 mayorista, son revendedores). Si en el futuro
  algún partner es institucional, se actualiza en el primer mensaje vía
  wa_account_id.
- Las 10 cadencias existentes quedan en client_type='mayorista' por default
  del campo (no hace falta tocarlas).
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Post-migration hook (corre DESPUÉS de cargar XML / actualizar schema).
    """
    # 1. Llenar client_type en memories existentes.
    # Heurística: si el partner tiene categoría Mayorista (16) o ya tiene
    # alguna fase mayorista en cadence_phase → mayorista. Si tiene
    # categoría EMPRESA (1) sin Mayorista → institucional. Sino → mayorista
    # (default conservador: todos los existentes vienen de Claudio v3.1).
    cr.execute("""
        UPDATE cristal_agent_memory mem
        SET client_type = 'mayorista'
        WHERE mem.client_type IS NULL OR mem.client_type = 'unknown'
    """)
    mayorista_count = cr.rowcount
    _logger.info(
        "✅ MIGRATION 1.9.0: %s memorias marcadas como 'mayorista' (default conservador)",
        mayorista_count
    )

    # 2. Detectar partners EMPRESA sin Mayorista y reclasificar como institucional.
    # Si tienen categoría EMPRESA (1) Y NO tienen Mayorista (16), son institucionales.
    cr.execute("""
        UPDATE cristal_agent_memory mem
        SET client_type = 'institucional'
        WHERE mem.partner_id IN (
            SELECT pcr.partner_id
            FROM res_partner_res_partner_category_rel pcr
            WHERE pcr.category_id = 1   -- EMPRESA
            AND pcr.partner_id NOT IN (
                SELECT partner_id
                FROM res_partner_res_partner_category_rel
                WHERE category_id = 16  -- Mayorista
            )
        )
    """)
    institucional_count = cr.rowcount
    _logger.info(
        "✅ MIGRATION 1.9.0: %s memorias reclasificadas a 'institucional' "
        "(partners con etiqueta EMPRESA sin Mayorista)",
        institucional_count
    )

    # 3. Asegurar que qualification_data exista (JSON vacío) en memorias previas.
    # Postgres maneja NULL → {} a través del default del field, pero por las
    # dudas hacemos explícito el reset.
    cr.execute("""
        UPDATE cristal_agent_memory
        SET qualification_data = '{}'::jsonb
        WHERE qualification_data IS NULL
    """)
    qual_count = cr.rowcount
    _logger.info("✅ MIGRATION 1.9.0: %s memorias con qualification_data inicializado", qual_count)

    _logger.info(
        "🎉 MIGRATION 1.9.0 completada. Total reclasificación: "
        "%s mayorista + %s institucional",
        mayorista_count - institucional_count,
        institucional_count,
    )
