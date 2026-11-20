# -*- coding: utf-8 -*-
"""v1.78 — Mensajes enviados desde el celular (WhatsApp Business app en convivencia).

Meta avisa de esos mensajes con el webhook `smb_message_echoes`, que Odoo estándar
descarta (solo procesa el campo `messages`). Sin esto, lo que Sergio contesta desde el
celular no queda en Odoo: el historial sale incompleto y nadie sabe que ya respondió.
La firma del pedido ya la validó el controlador original (si es inválida, corta antes).
"""
import json
import logging

from odoo import http
from odoo.http import request
from odoo.addons.whatsapp.controller.main import Webhook

_logger = logging.getLogger(__name__)


class CristalWhatsappWebhook(Webhook):

    @http.route()
    def webhookpost(self):
        res = super().webhookpost()
        try:
            data = json.loads(request.httprequest.data)
            for entry in data.get('entry', []):
                for change in entry.get('changes', []):
                    if change.get('field') != 'smb_message_echoes':
                        continue
                    value = change.get('value') or {}
                    phone_uid = (value.get('metadata') or {}).get('phone_number_id')
                    account = request.env['whatsapp.account'].sudo().search([
                        ('phone_uid', '=', phone_uid),
                        ('account_uid', '=', entry.get('id'))], limit=1)
                    if account:
                        account._cristal_process_echoes(value)
        except Exception:  # noqa: BLE001 — nunca romper la recepción de WhatsApp
            _logger.exception("No pude registrar los mensajes enviados desde el celular")
        return res
