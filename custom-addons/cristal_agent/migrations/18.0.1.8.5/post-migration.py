# -*- coding: utf-8 -*-
"""
Migración 18.0.1.8.5:
- Sanitización AUTOMÁTICA de variables en send_whatsapp_template
- Reemplaza \n, \r, \t por ". " (mantiene legibilidad sin saltos)
- Saca chars de control invisibles
- Colapsa múltiples espacios
- Limita a 1024 chars (Meta a veces rechaza más largo)

Resuelve definitivamente el error #132018 "There's an issue with the
parameters in your template" que ocurría cuando las ofertas vigentes
tenían saltos de línea en la description.

Aplica a todos los envíos automáticos: broadcast semanal, cadencias
proactivas y comandos del bot.
"""
import logging
_logger = logging.getLogger(__name__)

def migrate(cr, version):
    _logger.info("✅ MIGRATION 1.8.5: sanitización automática de variables template")
