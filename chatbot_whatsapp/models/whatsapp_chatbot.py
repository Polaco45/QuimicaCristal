from odoo import models, api, _
import openai
import logging
import os

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super(WhatsAppMessage, self).create(vals_list)
        for message in records:
            if message.state == 'received' and message.mobile_number and message.body:
                _logger.info("Mensaje recibido (ID %s): body = %s", message.id, message.body)

                try:
                    response = message._get_chatbot_response(message.body)
                except Exception as e:
                    _logger.error("Error al generar respuesta del chatbot: %s", str(e))
                    response = _("¡Gracias por tu mensaje! Enseguida te respondemos.")

                _logger.info("Respuesta cruda del chatbot para mensaje %s: %s", message.id, response)

                if response:
                    self.env['whatsapp.message'].create({
                        'body': response,
                        'mobile_number': message.mobile_number,
                        'wa_account_id': message.wa_account_id.id,
                        'direction': 'outgoing',
                        'state': 'in_queue',
                    })
        return records

    def _get_chatbot_response(self, user_message):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("No API key provided. Set the OPENAI_API_KEY environment variable.")
        
        openai.api_key = api_key

        prompt = f"""Sos un asistente de Química Cristal. Respondé de manera amable y clara. Si preguntan por un producto, sugerí los enlaces del sitio web si están publicados (is_published=True). El mensaje fue: {user_message}"""

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Sos un asistente de atención al cliente de Química Cristal."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=150,
        )
        return response.choices[0].message['content'].strip()
