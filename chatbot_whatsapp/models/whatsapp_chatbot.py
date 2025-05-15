# -*- coding: utf-8 -*-
from odoo import models, api
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        # Primero delegamos la creación original
        records = super(WhatsAppMessage, self).create(vals_list)
        for msg in records:
            # Solo nos interesan mensajes entrantes con cuenta y cuerpo
            if msg.state == 'received' and msg.body and msg.wa_account_id:
                _logger.info("Recibido en webhook: %s", msg.body)
                try:
                    # Creá el mensaje de respuesta
                    outgoing_vals = {
                        'wa_account_id': msg.wa_account_id.id,
                        'mobile_number': msg.mobile_number,
                        'body': "¡Hola! Hemos recibido tu mensaje. 😊",
                        'state': 'outgoing',
                    }
                    outgoing = self.env['whatsapp.message'].sudo().create(outgoing_vals)
                    # Intentá enviarlo inmediatamente
                    if hasattr(outgoing, '_send_message'):
                        outgoing._send_message()
                    _logger.info("Respuesta enviada a %s", msg.mobile_number)
                except Exception as e:
                    _logger.error("Error al enviar respuesta: %s", e)
        return records
