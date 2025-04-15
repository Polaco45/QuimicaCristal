from odoo import models, api
import openai
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model
    def create(self, vals):
        """
        Extiende la creación de mensajes de WhatsApp.
        Si el mensaje es 'received', llama a OpenAI para generar una respuesta
        y crea un mensaje saliente en 'outgoing' con el contenido.
        """
        record = super(WhatsAppMessage, self).create(vals)

        # Verificar si es mensaje entrante con texto
        if record.state == 'received' and record.body and record.mobile_number:
            try:
                # Llamar a OpenAI y obtener la respuesta
                answer = record._chatbot_openai_response(record.body)

                # Si el chatbot respondió algo no vacío
                if answer and answer.strip():
                    # Crear el mensaje de salida con el texto
                    # Queda en "en cola" -> Se encargará tu cron de enviarlo
                    # O si tenés un _send_message() disponible, lo podés llamar de inmediato.
                    self.env['whatsapp.message'].sudo().create({
                        'mobile_number': record.mobile_number,
                        'body': answer.strip(),
                        'state': 'outgoing',
                        'wa_account_id': record.wa_account_id.id if record.wa_account_id else False,
                        'create_uid': 2,  # ID Sergio Ramello (cambiá si es otro)
                    })
                else:
                    _logger.warning("Chatbot devolvió respuesta vacía para el mensaje %s", record.id)
            except Exception as e:
                _logger.error("Error generando respuesta para msg %s: %s", record.id, e)

        return record

    def _chatbot_openai_response(self, user_text):
        """
        Llama a la API de OpenAI usando ChatCompletion
        y retorna el texto generado, o None si falla.
        """
        try:
            api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not api_key:
                _logger.error("No se encontró la API Key de OpenAI.")
                return None

            openai.api_key = api_key
            resp = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Eres un bot de WhatsApp en Odoo. Responde en español, claro y conciso."},
                    {"role": "user", "content": user_text}
                ],
            )
            return resp.choices[0].message.content
        except Exception as e:
            _logger.error("Fallo al llamar OpenAI: %s", e)
            return None
