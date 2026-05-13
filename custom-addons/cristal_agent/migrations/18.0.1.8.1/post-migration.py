# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.8.1:
- PDF Lista Mayorista ahora agrupa productos por categoría (categ_id)
  Cada categoría con header naranja, productos debajo ordenados por prioridad.
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("✅ MIGRATION 1.8.1: PDF agrupado por categoría")
