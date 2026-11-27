# -*- coding: utf-8 -*-
"""v1.83.0 — WhatsApp de empresas en modo borrador. Deja cargada la cuenta "Cristal
Empresas" y a Joaco como quien aprueba, con el modo APAGADO, y pide el autotest."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([], limit=1)
    if not config:
        return
    vals = {'client_draft_selftest_log': 'pendiente'}
    if not config.client_draft_wa_account_id:
        account = env['whatsapp.account'].search([('name', 'ilike', 'Empresas')], limit=1)
        if account:
            vals['client_draft_wa_account_id'] = account.id
    config.write(vals)
    _logger.info("cristal_agent 1.83.0: modo borrador de empresas cargado (apagado): %s", vals)
