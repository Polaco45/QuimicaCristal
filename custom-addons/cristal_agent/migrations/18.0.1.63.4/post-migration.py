# -*- coding: utf-8 -*-
"""Migración 18.0.1.63.4 — Bandeja de entrada de Joaco (10/11/2026).

Marca como leídos los 1.287 avisos de la bandeja de entrada (1.165 eran "Te asignaron ..."
de OdooBot). De acá en más las actividades que crea OdooBot para Joaco no avisan
(models/mail_activity.py). Repite el silenciado de chats de WhatsApp por si quedó alguno.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Member = env["discuss.channel.member"]
    n_chats = Member._cristal_silenciar_whatsapp()
    n_inbox = Member._cristal_limpiar_bandeja()
    _logger.info("cristal_agent 18.0.1.63.4: %s chats silenciados, %s avisos de bandeja leídos", n_chats, n_inbox)
