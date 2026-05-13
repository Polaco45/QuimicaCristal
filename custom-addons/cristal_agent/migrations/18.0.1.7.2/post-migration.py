# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.7.2:
- Protección con getattr en hook canal interno (anti-crash en upgrade).
- Sin cambios en DB ni prompts.
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("✅ MIGRATION 1.7.2: hooks blindados con getattr")
