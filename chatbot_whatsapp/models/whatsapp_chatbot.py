# chatbot_whatsapp/models/whatsapp_chatbot.py
from odoo import models, api, fields, _
import openai
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'
    
    @api.model
    def create(self, vals):
        # Crear el mensaje original
        message = super(WhatsAppMessage, self).create(vals)

        # Verificar si el mensaje es recibido y tiene contenido válido
        if message.state == 'received' and message.mobile_number and message.body:
            chatbot_response = message._get_chatbot_response(message.body)
            if chatbot_response and chatbot_response.strip():
                response_vals = {
                    'mobile_number': message.mobile_number,
                    'body': chatbot_response.strip(),
                    'state': 'outgoing',
                    'create_uid': 2,  # ID del usuario Sergio Ramello
                }
                self.create(response_vals)
            else:
                _logger.warning("Respuesta vacía del chatbot. No se generó mensaje para: %s", message.body)

        return message

    def _get_chatbot_response(self, user_message):
        """
        Llama a la API de OpenAI para obtener una respuesta basada en el mensaje del usuario.
        """
        try:
            # Obtener la clave desde ir.config_parameter
            openai_api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not openai_api_key:
                _logger.error("La API key de OpenAI no está configurada en ir.config_parameter")
                return _("Lo siento, no se pudo procesar tu mensaje.")

            client = openai.OpenAI(api_key=openai_api_key)

            # Llamar a OpenAI con modelo actualizado
            response = client.chat.completions.create(
                model='gpt-3.5-turbo',
                messages=[
                    {
                        'role': 'system',
                        'content': 'Sos Sergio de Química Cristal. Respondé consultas de WhatsApp de forma amable, breve y clara.'
                    },
                    {
                        'role': 'user',
                        'content': user_message
                    }
                ]
            )
            return response.choices[0].message.content.strip()

        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e)
            return _("Ocurrió un error al obtener la respuesta.")
