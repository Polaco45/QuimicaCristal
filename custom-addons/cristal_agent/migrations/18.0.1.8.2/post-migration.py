# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.8.2:
- Fix race condition: increment_received/sent/escalation usan UPDATE SQL atómico
  → resuelve "could not serialize access due to concurrent update" cuando un
    cliente manda mensajes en ráfaga (3+ mensajes seguidos)
- Fix cascada InFailedSqlTransaction: si una tool detecta TX abortada, hace
  rollback y devuelve error claro al modelo en vez de propagar el error a
  todas las tools siguientes del loop
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("✅ MIGRATION 1.8.2: fix race condition + cascada de TX abortada")
