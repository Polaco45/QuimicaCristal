# -*- coding: utf-8 -*-
"""
Migración 18.0.1.25.0 — Operador: usar el número CON el 9 (entregable).

El WhatsApp de Joaco es +5493585481191 (con el 9 de móvil argentino). La
resolución anterior había quedado en un partner con el número SIN el 9
(+543585481191), y Meta acepta esos envíos ("sent") pero NO los entrega. Acá se
re-resuelve el partner operador prefiriendo el número CON el 9.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        _logger.warning("MIGRATION 1.25.0: no hay config activa")
        return

    Partner = env['res.partner']
    # Preferir el número CON el 9 (entregable por WhatsApp AR).
    p = Partner.search([('phone_sanitized', 'like', '%93585481191')], limit=1)
    if not p:
        p = Partner.search([('mobile', 'like', '93585481191')], limit=1)
    if p:
        config.owner_whatsapp_partner_id = p.id
        _logger.info("✅ MIGRATION 1.25.0: operador WhatsApp = %s (%s / %s)",
                     p.id, p.name, p.phone_sanitized or p.mobile)
    else:
        _logger.warning("MIGRATION 1.25.0: no encontré partner con el número CON 9; "
                        "queda el operador actual (%s)",
                        config.owner_whatsapp_partner_id.id if config.owner_whatsapp_partner_id else None)
