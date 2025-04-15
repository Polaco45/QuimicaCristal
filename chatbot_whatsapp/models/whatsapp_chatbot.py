from odoo import models, api, _
from openai import OpenAI
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model
    def create(self, vals):
        message = super(WhatsAppMessage, self).create(vals)

        if message.state == 'received' and message.mobile_number and message.body:
            chatbot_response = message._get_chatbot_response(message.body)
            if chatbot_response:
                response_vals = {
                    'mobile_number': message.mobile_number,
                    'body': chatbot_response,
                    'state': 'outgoing',
                    'create_uid': self.env.ref('base.user_admin').id,  # o el ID de Sergio Ramello
                }
                self.create(response_vals)
        return message

    def _get_chatbot_response(self, user_message):
        try:
            api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not api_key:
                _logger.error("API Key de OpenAI no configurada.")
                return _("Lo siento, no se pudo procesar tu mensaje.")

            client = OpenAI(api_key=api_key)

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Sos un asistente integrado en Odoo que responde mensajes de WhatsApp de forma clara y útil."},
                    {"role": "user", "content": user_message}
                ]
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e)
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
