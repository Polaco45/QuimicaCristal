# chatbot_whatsapp/models/whatsapp_chatbot.py
from odoo import models, api, _
import openai
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model
    def create(self, vals):
        # Crear el mensaje recibido
        message = super().create(vals)

        # Procesar si es entrante con número y texto
        if message.state == 'received' and message.mobile_number and message.body:
            response_text = message._get_chatbot_response(message.body)

            if response_text:
                try:
                    # Buscar usuario admin (Sergio Ramello)
                    user = self.env.ref('base.user_admin')
                except Exception as e:
                    _logger.warning("Fallo al asignar usuario Sergio Ramello: %s", e)
                    user = self.env.uid  # fallback

                # Crear el mensaje saliente manualmente
                self.with_user(user).sudo().create({
                    'mobile_number': message.mobile_number,
                    'body': response_text,  # <-- Guardamos el texto ANTES de cambiar usuario
                    'state': 'outgoing',
                    'wa_account_id': message.wa_account_id.id,
                })

        return message

    def _get_chatbot_response(self, user_message):
        try:
            api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not api_key:
                _logger.error("API key de OpenAI no encontrada")
                return _("Lo siento, no pude responder tu mensaje.")
            openai.api_key = api_key

            respuesta = openai.ChatCompletion.create(
                model='gpt-3.5-turbo',
                messages=[
                    {
                        'role': 'system',
                        'content': 'Sos un asistente para clientes de Química Cristal. Respondé dudas de limpieza de forma profesional y clara.'
                    },
                    {
                        'role': 'user',
                        'content': user_message
                    }
                ]
            )
            return respuesta.choices[0].message['content'].strip()
        except Exception as e:
            _logger.error("Error de OpenAI: %s", e)
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
