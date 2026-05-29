# -*- coding: utf-8 -*-
"""
Migración 18.0.1.9.1 — Tools de cierre atómico institucional.

Agrega 2 tools sin cambios de schema:
- update_qualification_data: guarda progreso en memory.qualification_data
- complete_institutional_qualification: cierre atómico (empresa + lead + activity + takeover)

No requiere migración de datos (las tools se auto-registran al instalar).
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("✅ MIGRATION 1.9.1: tools de cierre institucional disponibles")
