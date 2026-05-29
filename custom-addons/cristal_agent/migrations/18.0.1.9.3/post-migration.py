# -*- coding: utf-8 -*-
"""
Migración 18.0.1.9.3 — Fix pricelist L.E 2 en flow institucional.

Bug fix:
- En complete_institutional_qualification, branch SIN factura, la pricelist
  L.E 2 no se aplicaba porque la condición era "si no tiene pricelist". Pero
  Odoo asigna pricelist por default al crear partner (L.C 1 típicamente),
  entonces nunca llegaba a poner L.E 2.
- Branch CON factura, empresa existente: misma lógica, no pisaba pricelist.

Fix: forzar L.E 2 SIEMPRE al completar calificación institucional, sin
respetar default de Odoo. Regla del brief: institucional = L.E 2.
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("✅ MIGRATION 1.9.3: fix pricelist L.E 2 en flow institucional")
