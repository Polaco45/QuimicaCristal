# -*- coding: utf-8 -*-
"""
Migración 18.0.1.9.5 — Reestructuración visual del menú.

Cambios:
- Menú reorganizado en 2 apartados gemelos: 📦 Mayorista + 🏢 Institucional
- Cada apartado tiene: Conversaciones, Ejecuciones, Partners, Cadencias, Config
- Sección Institucional extra: Calificaciones en curso + Leads calificados
- Vista kanban nueva para memorias (agrupada por client_type)
- Campo res.partner.agent_memory_id (computed) para filtrar runs por tipo
- Actions filtradas por client_type (memorias, runs, cadencias, partners)

Sin cambios de schema.
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("✅ MIGRATION 1.9.5: menú reestructurado + vista kanban + actions filtradas")
