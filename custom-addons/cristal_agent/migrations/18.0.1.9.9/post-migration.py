# -*- coding: utf-8 -*-
"""
Migración 18.0.1.9.9 — Knowledge filtrado por client_type (mayorista/institucional).

Bug fix: el bot institucional (cuenta Compras) leía la knowledge "derivar a Compras"
y derivaba al cliente de regreso al mismo canal (loop circular).

Cambios:
- Campo nuevo: cristal.agent.knowledge.client_type_filter (both/mayorista/institucional)
- prompt_builder filtra knowledge según el client_type del bot actual
- search_knowledge tool (que el bot llama) también filtra por client_type del partner

Auto-setea:
- Knowledge ID 50 (derivar a Compras) → client_type_filter = 'mayorista'
- Knowledge ID 51 (derivar a Crilimp) → client_type_filter = 'institucional'
- Todas las demás knowledge → 'both' (default, sin cambios)
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("⚙️  MIGRATION 1.9.9: knowledge filtrado por canal")

    # Marcar knowledge 50 como mayorista-only
    cr.execute("""
        UPDATE cristal_agent_knowledge
        SET client_type_filter = 'mayorista'
        WHERE id = 50
    """)
    rows_50 = cr.rowcount

    # Marcar knowledge 51 como institucional-only
    cr.execute("""
        UPDATE cristal_agent_knowledge
        SET client_type_filter = 'institucional'
        WHERE id = 51
    """)
    rows_51 = cr.rowcount

    _logger.info(
        "✅ Knowledge 50 (Crilimp→Compras) seteado a 'mayorista': %d row, "
        "Knowledge 51 (Compras→Crilimp) seteado a 'institucional': %d row",
        rows_50, rows_51
    )
