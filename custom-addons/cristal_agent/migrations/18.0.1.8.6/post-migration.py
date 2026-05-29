# -*- coding: utf-8 -*-
"""
Migración 18.0.1.8.6:
- Knowledge entries con priority >= 100 NO se truncan más en el prompt
  (antes se cortaban a 350 chars y el bot perdía el protocolo completo).
- Se muestran en una sección destacada "🚨 CAMPAÑAS/ALERTAS ACTIVAS" al inicio.
- Detección de partners duplicados por mobile: cuando el mismo número está
  cargado en >1 partner, el bot recibe aviso para saludar sin nombre.
- User message refuerza: "si hay campañas activas, aplicar SIN omitir partes".

Resuelve: bot respondiendo a PROMO sin revelar el secreto del 20%, y
confusiones de nombre por duplicados (caso Liliana/Florencia Rodriguez).
"""
import logging
_logger = logging.getLogger(__name__)

def migrate(cr, version):
    _logger.info("✅ MIGRATION 1.8.6: campañas activas no se truncan + detección duplicados")
