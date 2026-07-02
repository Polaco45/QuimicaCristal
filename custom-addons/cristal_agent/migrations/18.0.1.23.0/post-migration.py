# -*- coding: utf-8 -*-
"""
Migración 18.0.1.23.0 — Nombre en los chats de WhatsApp.

Los canales de WhatsApp se crean con el número como nombre. El nombre real del
contacto (perfil de WhatsApp) ya está en whatsapp_partner_id. Este backfill copia
ese nombre al nombre del canal para todos los chats existentes, así Joaco los
identifica de un vistazo (en vez de ver una lista de números).
"""
import logging
import re

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def _bare_number(txt):
    if not txt:
        return True
    return re.sub(r'[\s\-\+()]', '', txt).isdigit()


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Channel = env['discuss.channel'].sudo()
    channels = Channel.search([('channel_type', '=', 'whatsapp')])
    renamed = 0
    for ch in channels:
        wa_partner = ch.whatsapp_partner_id
        real_name = (wa_partner.name or '').strip() if wa_partner else ''
        if not real_name or _bare_number(real_name):
            continue
        if (ch.name or '').strip() != real_name:
            ch.write({'name': real_name})
            renamed += 1
    _logger.info("✅ MIGRATION 1.23.0: %s/%s chats de WhatsApp renombrados con el nombre del contacto",
                 renamed, len(channels))
