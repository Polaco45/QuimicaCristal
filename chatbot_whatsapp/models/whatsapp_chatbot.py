# -*- coding: utf-8 -*-
from odoo import models, api, fields, _
import openai
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'
    
    @api.model
    def create(self, vals):
        # Creamos el mensaje normalmente
        message = super(WhatsAppMessage, self).create(vals)
        
        # Si el mensaje es entrante y tiene contenido, llamamos al chatbot
        if message.direction == 'inbound' and message.mobile_number and message.message:
            chatbot_response = message._get_chatbot_response(message.message)
            if chatbot_response:
                # Creamos un nuevo mensaje de salida para responder
                response_vals = {
                    'mobile_number': message.mobile_number,  # Se responde al mismo número
                    'message': chatbot_response,
                    'direction': 'outbound',
                    # Agrega aquí otros campos necesarios (por ejemplo, usuario, fecha, etc.)
                }
                self.create(response_vals)
        return message

    def _get_chatbot_response(self, user_message):
        """
        Llama a la API de OpenAI para obtener una respuesta basada en el mensaje del usuario.
        """
        try:
            # Recuperar la API key desde los parámetros del sistema
            openai_api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not openai_api_key:
                _logger.error("La API key de OpenAI no está configurada en ir.config_parameter")
                return _("Lo siento, no se pudo procesar tu mensaje.")
            openai.api_key = openai_api_key
            
            # Llamar a la API de OpenAI utilizando el modelo gpt-3.5-turbo
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
