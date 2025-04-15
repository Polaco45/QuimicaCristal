from odoo import models, api, _
import openai
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        # Se crean uno o varios mensajes
        records = super(WhatsAppMessage, self).create(vals_list)
        for message in records:
            # Procesamos sólo si es mensaje entrante con state 'received' y con número y cuerpo definidos
            if message.state == 'received' and message.mobile_number and message.body:
                _logger.info("Mensaje recibido (ID %s): body = %s", message.id, message.body)
                chatbot_response = message._get_chatbot_response(message.body)
                _logger.info("Respuesta cruda del chatbot para mensaje %s: %s", message.id, chatbot_response)
                # Usamos la respuesta si no es vacía; de lo contrario, asignamos un mensaje predeterminado
                if chatbot_response and chatbot_response.strip():
                    response_text = chatbot_response.strip()
                else:
                    response_text = _("Lo siento, no pude procesar tu consulta.")
                    _logger.warning("La respuesta del chatbot quedó vacía para el mensaje %s", message.id)
                try:
                    outgoing_vals = {
                        'mobile_number': message.mobile_number,
                        'body': response_text,  # Valor inicial enviado
                        'state': 'outgoing',
                        'create_uid': self.env.ref('base.user_admin').id,  # Asigna el usuario (modificar si es distinto)
                        'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
                    }
                    outgoing_msg = self.env['whatsapp.message'].sudo().create(outgoing_vals)
                    # Forzar la escritura del contenido en 'body'
                    outgoing_msg.sudo().write({'body': response_text})
                    _logger.info("Mensaje saliente creado: ID %s, body = %s", outgoing_msg.id, outgoing_msg.body)
                    # Si existe método para enviar el mensaje, invocarlo
                    if hasattr(outgoing_msg, '_send_message'):
                        outgoing_msg._send_message()
                    else:
                        _logger.info("No se encontró _send_message; el mensaje quedará en cola.")
                except Exception as e:
                    _logger.error("Error al crear/enviar el mensaje saliente para el registro %s: %s", message.id, e)
        return records

    def _get_chatbot_response(self, user_message):
        """
        Llama a la API de OpenAI para obtener una respuesta basada en el mensaje del usuario.
        """
        try:
            api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not api_key:
                _logger.error("La API key de OpenAI no está configurada en ir.config_parameter")
                return _("Lo siento, no pude procesar tu mensaje.")
            openai.api_key = api_key

            response = openai.ChatCompletion.create(
                model='gpt-3.5-turbo',
                messages=[
                    {"role": "system", "content": "Sos un asistente de atención al cliente de Química Cristal. Respondé de forma clara, amable y concisa."},
                    {"role": "user", "content": user_message}
                ]
            )
            _logger.info("Respuesta completa de OpenAI para el mensaje '%s': %s", user_message, response)
            # Intentar acceder al contenido; probamos de dos maneras
            try:
                answer = response.choices[0].message.content.strip()
            except Exception:
                answer = response.choices[0].message['content'].strip()
            return answer
        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e, exc_info=True)
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
