# chatbot_whatsapp/models/whatsapp_chatbot.py
from odoo import models, api, fields, _
from openai import OpenAI
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model
    def create(self, vals):
        # Se crea el mensaje normalmente
        message = super(WhatsAppMessage, self).create(vals)

        # Verifica si el mensaje es entrante y tiene contenido
        if message.state == 'received' and message.mobile_number and message.body:
            chatbot_response = message._get_chatbot_response(message.body)
            if chatbot_response:
                response_vals = {
                    'mobile_number': message.mobile_number,
                    'body': chatbot_response,
                    'state': 'outgoing',
                }
                self.create(response_vals)
        return message

    def _get_chatbot_response(self, user_message):
        """
        Llama a la API de OpenAI para obtener una respuesta basada en el mensaje del usuario.
        """
        try:
            api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not api_key:
                _logger.error("La API key de OpenAI no está configurada en ir.config_parameter")
                return _("Lo siento, no se pudo procesar tu mensaje.")

            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model='gpt-3.5-turbo',
                messages=[
                    {'role': 'system', 'content': 'Sos un asistente que responde por WhatsApp desde Odoo.'},
                    {'role': 'user', 'content': user_message},
                ]
            )
            return response.choices[0].message.content.strip()

        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e)
            return _("Ocurrió un error al obtener la respuesta.")
