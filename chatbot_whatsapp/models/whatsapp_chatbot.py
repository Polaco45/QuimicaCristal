# chatbot_whatsapp/models/whatsapp_chatbot.py
from odoo import models, api, _
import openai
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model
    def create(self, vals):
        # Crear el mensaje entrante
        message = super(WhatsAppMessage, self).create(vals)

        # Procesar solo si es recibido y tiene contenido
        if message.state == 'received' and message.mobile_number and message.body:
            response_text = message._get_chatbot_response(message.body)

            if response_text:
                try:
                    # Buscar el usuario Sergio Ramello (admin)
                    user = self.env.ref('base.user_admin')
                except Exception as e:
                    _logger.warning("No se encontró el usuario Sergio Ramello: %s", e)
                    user = self.env.uid  # Fallback

                # Crear la respuesta en estado "outgoing"
                self.with_user(user).create({
                    'mobile_number': message.mobile_number,
                    'body': response_text,
                    'state': 'outgoing',
                    'wa_account_id': message.wa_account_id.id,
                })

        return message

    def _get_chatbot_response(self, user_message):
        try:
            api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not api_key:
                _logger.error("La API key de OpenAI no está configurada")
                return _("Lo siento, no pude procesar tu mensaje.")
            openai.api_key = api_key

            respuesta = openai.ChatCompletion.create(
                model='gpt-3.5-turbo',
                messages=[
                    {
                        'role': 'system',
                        'content': 'Sos un asistente de atención al cliente de una empresa de productos de limpieza. Respondé de forma clara, profesional y empática.'
                    },
                    {
                        'role': 'user',
                        'content': user_message
                    }
                ]
            )
            return respuesta.choices[0].message['content'].strip()
        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e)
            return _("Hubo un error al generar la respuesta.")
