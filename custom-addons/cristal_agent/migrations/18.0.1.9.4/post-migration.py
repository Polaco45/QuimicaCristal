# -*- coding: utf-8 -*-
"""
Migración 18.0.1.9.4 — Vistas UI actualizadas.

Cambios:
- Vista config: agregada tab "Institucional" para editar system_prompt_institutional
- Vista memory: agregado client_type + qualification_data visible
- Sin cambios de schema
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("✅ MIGRATION 1.9.4: vistas UI actualizadas (config + memory)")
