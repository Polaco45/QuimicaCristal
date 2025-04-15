from odoo import models, api, _
import openai
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super(WhatsAppMessage, self).create(vals_list)
        for message in records:
            if message.state == 'received' and message.mobile_number and message.body:
                _logger.info("Mensaje recibido (ID %s): body = %s", message.id, message.body)
                chatbot_response = message._get_chatbot_response(message.body)
                _logger.info("Respuesta cruda del chatbot para mensaje %s: %s", message.id, chatbot_response)

                response_text = chatbot_response.strip() if chatbot_response and chatbot_response.strip() else _("Lo siento, no pude procesar tu consulta.")
                if not chatbot_response or not chatbot_response.strip():
                    _logger.warning("La respuesta del chatbot quedó vacía para el mensaje %s", message.id)

                try:
                    outgoing_vals = {
                        'mobile_number': message.mobile_number,
                        'body': response_text,
                        'state': 'outgoing',
                        'create_uid': self.env.ref('base.user_admin').id,
                        'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
                    }
                    outgoing_msg = self.env['whatsapp.message'].sudo().create(outgoing_vals)
                    outgoing_msg.sudo().write({'body': response_text})
                    _logger.info("Mensaje saliente creado: ID %s, body = %s", outgoing_msg.id, outgoing_msg.body)

                    if hasattr(outgoing_msg, '_send_message'):
                        outgoing_msg._send_message()
                    else:
                        _logger.info("No se encontró _send_message; el mensaje quedará en cola.")
                except Exception as e:
                    _logger.error("Error al crear/enviar el mensaje saliente para el registro %s: %s", message.id, e)
        return records

    def _get_chatbot_response(self, user_message):
        """
        Llama a la API de OpenAI con contexto del último mensaje de ese número.
        """
        try:
            api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not api_key:
                _logger.error("La API key de OpenAI no está configurada en ir.config_parameter")
                return _("Lo siento, no pude procesar tu mensaje.")

            openai.api_key = api_key

            # Recuperamos último mensaje anterior de este número
            last_message = self.env['whatsapp.message'].sudo().search([
                ('mobile_number', '=', self.mobile_number),
                ('id', '<', self.id),
                ('state', '=', 'received'),
                ('body', '!=', False)
            ], order="id desc", limit=1).body or ''

            # Armamos el contexto
            messages = [
                {"role": "system", "content": "Sos un asistente de atención al cliente de Química Cristal. Respondé de forma clara, amable y concisa."},
                {"role": "user", "content": str(last_message)},
                {"role": "user", "content": str(user_message)}
            ]

            response = openai.ChatCompletion.create(
                model='gpt-3.5-turbo',
                messages=messages
            )

            _logger.info("Respuesta completa de OpenAI para el mensaje '%s': %s", user_message, response)
            try:
                return response.choices[0].message.content.strip()
            except Exception:
                return response.choices[0].message['content'].strip()
        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e, exc_info=True)
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
