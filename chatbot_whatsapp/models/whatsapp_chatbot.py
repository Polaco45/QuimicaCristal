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

                if chatbot_response and chatbot_response.strip():
                    response_text = chatbot_response.strip()
                else:
                    response_text = _("Lo siento, no pude procesar tu consulta.")
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

    def _get_recent_conversation(self, limit=5):
        """
        Obtiene los últimos mensajes del mismo número antes del actual.
        """
        return self.env['whatsapp.message'].sudo().search(
            [
                ('mobile_number', '=', self.mobile_number),
                ('create_date', '<=', self.create_date),
            ],
            order='create_date desc',
            limit=limit
        )

    def _get_chatbot_response(self, user_message):
        try:
            api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not api_key:
                _logger.error("La API key de OpenAI no está configurada en ir.config_parameter")
                return _("Lo siento, no pude procesar tu mensaje.")
            openai.api_key = api_key

            # Agregar historial al contexto
            context_messages = []
            recent_messages = self._get_recent_conversation()
            for msg in reversed(recent_messages):  # del más antiguo al más nuevo
                role = 'user' if msg.state == 'received' else 'assistant'
                context_messages.append({"role": role, "content": msg.body})

            context_messages.append({"role": "user", "content": user_message})

            response = openai.ChatCompletion.create(
                model='gpt-3.5-turbo',
                messages=[
                    {
                        "role": "system",
                        "content": "Sos un asistente virtual de Química Cristal. Respondé consultas con claridad, simpatía y en un tono institucional."
                    }
                ] + context_messages
            )

            _logger.info("Respuesta completa de OpenAI para el mensaje '%s': %s", user_message, response)
            try:
                answer = response.choices[0].message.content.strip()
            except Exception:
                answer = response.choices[0].message['content'].strip()
            return answer

        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e, exc_info=True)
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
