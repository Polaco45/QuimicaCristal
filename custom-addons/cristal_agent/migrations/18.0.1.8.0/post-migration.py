# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.8.0:
- Templates WhatsApp default creados automáticamente (en draft)
- Bot SOLO actúa en cuenta WA Crilimp por default
- Restricted_wa_account_ids como filtro de cuentas

Después del upgrade, Joaco solo tiene que ir a WhatsApp → Templates y
mandar a aprobación los templates nuevos. Cuando estén approved, el bot
los usa automáticamente.
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        from odoo.addons.cristal_agent.services.templates_setup import ensure_default_templates
        result = ensure_default_templates(env)
        _logger.info(
            "✅ MIGRATION 1.8.0: templates → creados=%s, ya existían=%s, "
            "asignados a cadencias=%s, cuenta Crilimp id=%s",
            result['created'], result['skipped'], result['assigned_to_cadence'],
            result['crilimp_account_id']
        )
    except Exception as e:
        _logger.exception("MIGRATION 1.8.0: %s", e)
