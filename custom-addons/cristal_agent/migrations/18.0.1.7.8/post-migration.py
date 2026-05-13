# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.7.8:
- Cron nuevo cron_weekly_offer_broadcast (lunes 14hs ARG → 17:00 UTC)
- Nueva cadencia: "Recordatorio 30 días sin recompra" (entre 14d y 45d)
- Campos nuevos en config: enable_weekly_offer_broadcast, weekly_offer_template_id
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        cadences = env['cristal.agent.cadence'].sudo().search([('active', '=', True)])
        templates = env['whatsapp.template'].sudo().search([('status', '=', 'approved')])
        _logger.info(
            "✅ MIGRATION 1.7.8: %s cadencias activas, %s templates aprobados",
            len(cadences), len(templates)
        )
    except Exception as e:
        _logger.exception("MIGRATION 1.7.8: %s", e)
