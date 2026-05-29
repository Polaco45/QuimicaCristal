# -*- coding: utf-8 -*-
"""
Migración 18.0.1.8.4:
- send_whatsapp_template ahora detecta el modelo del template (crm.lead vs res.partner)
- Si el template usa crm.lead (caso común con variables tipo partner_id.name),
  busca o crea un lead asociado al partner para que el composer pueda renderizar
- Variables free_text como campos individuales (free_text_1, free_text_2, ...)
  en vez de free_text_json (que NO existe en whatsapp.composer de Odoo 18)
- Mobile normalizado (sin espacios ni guiones)

Resuelve definitivamente el broadcast de templates que estaba fallando.
"""
import logging
_logger = logging.getLogger(__name__)

def migrate(cr, version):
    _logger.info("✅ MIGRATION 1.8.4: send_whatsapp_template robusto multi-modelo")
