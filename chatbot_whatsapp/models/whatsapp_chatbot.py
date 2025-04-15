# chatbot_whatsapp/models/whatsapp_chatbot.py
from odoo import models, api, fields, _
import openai
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'
    
    @api.model
    def create(self, vals):
        # Se crea el mensaje normalmente
        message = super(WhatsAppMessage, self).create(vals)
        
        # Se verifica que el mensaje sea entrante (state == 'received'),
        # y que disponga de un número de teléfono y contenido en body.
        if message.state == 'received' and message.mobile_number and message.body:
            chatbot_response = message._get_chatbot_response(message.body)
            if chatbot_response:
                # Se crea un nuevo mensaje de salida (outgoing)
                response_vals = {
                    'mobile_number': message.mobile_number,  # Responder al mismo número
                    'body': chatbot_response,                 # El contenido de la respuesta
                    'state': 'outgoing',                      # Se asume que 'outgoing' indica mensaje en cola para enviar
                    # Puedes agregar otros campos si es necesario (por ejemplo, fecha o usuario)
                }
                self.create(response_vals)
        return message

    def _get_chatbot_response(self, user_message):
        """
        Llama a la API de OpenAI para obtener una respuesta basada en el mensaje del usuario.
        """
        try:
            # Recupera la API key desde los parámetros del sistema
            openai_api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not openai_api_key:
                _logger.error("La API key de OpenAI no está configurada en ir.config_parameter")
                return _("Lo siento, no se pudo procesar tu mensaje.")
            openai.api_key = openai_api_key
            
            # Llama a la API de OpenAI utilizando el modelo gpt-3.5-turbo
            openai_response = openai.ChatCompletion.create(
                model='gpt-3.5-turbo',
                messages=[
                    {
                        'role': 'system',
                        'content': 'Eres un asistente integrado en Odoo que responde mensajes de WhatsApp de forma clara y concisa.'
                    },
                    {
                        'role': 'user',
                        'content': user_message
                    }
                ]
            )
            respuesta = openai_response.choices[0].message['content'].strip()
            return respuesta
        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e)
            return _("Ocurrió un error al obtener la respuesta.")
