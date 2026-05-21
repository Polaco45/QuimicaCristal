# -*- coding: utf-8 -*-
"""
Migración 18.0.1.8.3:
- send_whatsapp_template ahora usa whatsapp.composer (flujo nativo Odoo)
- Formato free_text_json corregido: {"free_text_1": "..."} en vez de
  {"body": {"1": "..."}} (formato viejo que Meta rechazaba)
- mobile_number normalizado (saca espacios, guiones, paréntesis)

Resuelve broadcast semanal que fallaba con "calificación de calidad
demasiado baja" y "formato de número incorrecto".
"""
import logging
_logger = logging.getLogger(__name__)

def migrate(cr, version):
    _logger.info("✅ MIGRATION 1.8.3: send_whatsapp_template usa composer nativo")
