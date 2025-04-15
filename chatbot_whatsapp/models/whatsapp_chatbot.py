from odoo import models, api, fields, _
import openai
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model
    def create(self, vals):
        message = super(WhatsAppMessage, self).create(vals)

        if message.state == 'received' and message.mobile_number and message.body:
            chatbot_response = message._get_chatbot_response(message.body)
            if chatbot_response and chatbot_response.strip():
                respuesta = self.sudo().create({
                    'mobile_number': message.mobile_number,
                    'body': chatbot_response.strip(),
                    'state': 'outgoing',
                    'create_uid': 2,  # Sergio Ramello
                    'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
                    'x_studio_contacto': message.x_studio_contacto.id if message.x_studio_contacto else False,
                })
                respuesta._send_message()  # 🔥 Enviamos el mensaje automático al instante
            else:
                _logger.warning("Respuesta vacía del chatbot. No se generó mensaje para: %s", message.body)

        return message

    def _get_chatbot_response(self, user_message):
        try:
            openai_api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not openai_api_key:
                _logger.error("La API key de OpenAI no está configurada en ir.config_parameter")
                return _("Lo siento, no se pudo procesar tu mensaje.")

            openai.api_key = openai_api_key

            response = openai.ChatCompletion.create(
                model='gpt-3.5-turbo',
                messages=[
                    {
                        'role': 'system',
                        'content': 'Sos el asistente automático de Química Cristal. Respondé consultas de clientes de manera clara, amable y precisa.'
                    },
                    {
                        'role': 'user',
                        'content': user_message
                    }
                ]
            )
            return response.choices[0].message['content'].strip()

        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e)
            return _("Ocurrió un error al obtener la respuesta.")
