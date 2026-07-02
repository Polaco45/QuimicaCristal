# -*- coding: utf-8 -*-
"""
Migración 18.0.1.22.0 — Calificación (mayorista) + operador por WhatsApp.

- Recarga el prompt v4 (calificación reforzada: micro-emprendimiento de limpieza =
  MAYORISTA; ante la duda preguntar, nunca derivar por las dudas).
- Configura el canal de operador por WhatsApp: número de Joaco (3585481191) y su
  partner (para mandarle notificaciones con la plantilla). Los mensajes DESDE ese
  número se tratan como órdenes del operador; las urgencias/confirmaciones le
  llegan por WhatsApp (el canal interno queda como log de respaldo).
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        _logger.warning("MIGRATION 1.22.0: no hay config activa")
        return

    # 1) Recargar prompt v4 (calificación reforzada)
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v4.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v4'})
        _logger.info("✅ MIGRATION 1.22.0: prompt v4 recargado (%s chars)", len(content))

    # 2) Número del operador
    if not config.owner_whatsapp_number:
        config.owner_whatsapp_number = '3585481191'
    if config.notify_owner_via_whatsapp is False and config.notify_owner_via_whatsapp is not True:
        config.notify_owner_via_whatsapp = True

    # 3) Resolver / crear el partner del operador (WhatsApp de Joaco)
    Partner = env['res.partner']
    p = Partner.search([
        '|', ('phone_sanitized', '=', '+5493585481191'),
        ('phone_sanitized', '=', '+543585481191')], limit=1)
    if not p:
        p = Partner.search([('phone_sanitized', 'like', '3585481191')], limit=1)
    if not p:
        p = Partner.search(['|', ('mobile', 'like', '3585481191'),
                            ('phone', 'like', '3585481191')], limit=1)
    if not p:
        p = Partner.create({
            'name': 'Joaquín (Operador Claudio)',
            'mobile': '+5493585481191',
        })
        _logger.info("🆕 MIGRATION 1.22.0: creado partner operador %s", p.id)
    config.owner_whatsapp_partner_id = p.id
    _logger.info("✅ MIGRATION 1.22.0: operador WhatsApp = partner %s (%s)", p.id, p.name)
