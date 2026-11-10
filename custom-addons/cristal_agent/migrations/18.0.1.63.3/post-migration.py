# -*- coding: utf-8 -*-
"""Migración 18.0.1.63.3 — Notificaciones de WhatsApp (10/11/2026).

Joaco pidió dejar de recibir las 1.491 notificaciones de chats de WhatsApp y los avisos
"Desfijó su conversación con X". Esta migración marca como leídos y silencia todos sus chats
de WhatsApp existentes; los nuevos nacen silenciados (models/discuss_channel_member.py) y el
aviso de desfijado se descarta en el cliente (static/src/js/avisos_silenciosos.js).
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    n = env["discuss.channel.member"]._cristal_silenciar_whatsapp()
    _logger.info("cristal_agent 18.0.1.63.3: %s chats de WhatsApp silenciados", n)
