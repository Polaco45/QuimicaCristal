# -*- coding: utf-8 -*-
"""Migración 18.0.1.77.0 — Compras en modo consulta (pedido de Sergio, 18/11/2026).

Deja cargados la cuenta de WhatsApp de Compras y el responsable (Sergio), con el modo
APAGADO: se prende a mano desde Cristal Agent → Sistema → Configuración cuando Sergio dé
el OK. No cambia nada del agente de ventas.
"""
import logging
import re

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        return
    Account = env['whatsapp.account']
    account = Account
    raw = env['ir.config_parameter'].get_param('sistemas.wa_cuentas_fuera_de_clientes') or ''
    ids = [int(x) for x in re.findall(r'\d+', raw)]
    if ids:
        account = Account.browse(ids[0]).exists()
    if not account:
        account = Account.search([('name', '=ilike', 'Química Cristal Compras')], limit=1)
    owner = env.ref('base.user_admin', raise_if_not_found=False)
    vals = {}
    if account and not config.purchase_wa_account_id:
        vals['purchase_wa_account_id'] = account.id
    if owner and not config.purchase_owner_user_id:
        vals['purchase_owner_user_id'] = owner.id
        if owner.partner_id.mobile and not config.purchase_owner_whatsapp_number:
            vals['purchase_owner_whatsapp_number'] = owner.partner_id.mobile
    if vals:
        config.write(vals)
    _logger.info("Compras en modo consulta: cuenta %s, responsable %s, apagado.",
                 account.display_name if account else '—', owner.name if owner else '—')
