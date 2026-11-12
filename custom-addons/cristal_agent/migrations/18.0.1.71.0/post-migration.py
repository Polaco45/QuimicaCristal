# -*- coding: utf-8 -*-
"""Migración 18.0.1.71.0 — Joaco (12/11/2026): "Alejandra no visita mayoristas por ahora,
me cargás una llamada a mí". Las llamadas del motor (cotización grande que vence, cliente
dormido) pasan al usuario de Joaco."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    owner = config.owner_partner_id.user_ids[:1] if config and config.owner_partner_id else False
    if config and owner and config.lifecycle_visit_user_id != owner:
        config.lifecycle_visit_user_id = owner.id
        _logger.info("✅ MIGRATION 1.71.0: llamadas del motor → %s", owner.name)
