# -*- coding: utf-8 -*-
"""
Migración 18.0.1.11.1 — Acción de broadcast de campaña.

- Nueva acción server-side "Enviar campaña WhatsApp" sobre crm.lead (menú
  Acciones): manda el template configurado en config.campaign_template_id a
  todos los leads seleccionados, sin el límite de iteraciones del bot.
- Esta migración deja campaign_template_id apuntando al template
  'combo_mayorista_hoy' si existe y está aprobado (para la campaña de esta
  semana). Si no, lo deja vacío y se configura desde la UI.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        _logger.warning("MIGRATION 1.11.1: no hay config activa")
        return

    if config.campaign_template_id:
        _logger.info("MIGRATION 1.11.1: campaign_template_id ya configurado, no piso")
        return

    tmpl = env['whatsapp.template'].search([
        ('name', '=', 'combo_mayorista_hoy'),
        ('status', '=', 'approved'),
    ], limit=1)
    if tmpl:
        config.campaign_template_id = tmpl.id
        _logger.info(
            "✅ MIGRATION 1.11.1: campaign_template_id = '%s' (id=%s)",
            tmpl.name, tmpl.id)
    else:
        _logger.info(
            "MIGRATION 1.11.1: no encontré template 'combo_mayorista_hoy' aprobado; "
            "configuralo manualmente en Cristal Agent → Configuración.")
