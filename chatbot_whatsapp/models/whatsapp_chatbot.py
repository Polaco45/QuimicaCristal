from odoo import models, api, _
import openai
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model
    def create(self, vals):
        message = super().create(vals)

        # Solo responder si es un mensaje entrante válido
        if message.state == 'received' and message.mobile_number and message.body:
            chatbot_response = message._get_chatbot_response(message.body)

            # Validamos que haya una respuesta generada
            if chatbot_response and chatbot_response.strip():
                respuesta_texto = chatbot_response.strip()
            else:
                respuesta_texto = _("Lo siento, no pude procesar tu consulta.")

            # Creamos un mensaje nuevo con la respuesta
            try:
                new_msg = self.sudo().create({
                    'mobile_number': message.mobile_number,
                    'body': respuesta_texto,
                    'state': 'outgoing',
                    'create_uid': 2,  # Sergio Ramello
                    'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
                    'x_studio_contacto': message.x_studio_contacto.id if message.x_studio_contacto else False,
                })

                # Confirmamos que se guardó el cuerpo antes de enviarlo
                if new_msg.body:
                    new_msg._send_message()
                else:
                    _logger.error("El mensaje no tiene contenido en 'body', no se enviará.")
            except Exception as e:
                _logger.error("Error al crear o enviar mensaje automático: %s", e)

        return message

    def _get_chatbot_response(self, user_message):
        try:
            openai_api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not openai_api_key:
                _logger.error("API key de OpenAI no configurada.")
                return _("Lo siento, no se pudo procesar tu mensaje.")

            openai.api_key = openai_api_key

            response = openai.ChatCompletion.create(
                model='gpt-3.5-turbo',
                messages=[
                    {"role": "system", "content": "Sos un asistente de atención al cliente de Química Cristal. Respondé de forma clara, amable y directa."},
                    {"role": "user", "content": user_message}
                ]
            )

            return response.choices[0].message['content'].strip()

        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e)
            return _("Ocurrió un error al obtener la respuesta.")
