from odoo import models, api, fields, _
import openai
import logging

_logger = logging.getLogger(__name__)


class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        for message in messages:
            if message.state == 'received' and message.mobile_number and message.body:
                message._generate_chatbot_response()
        return messages

    def _generate_chatbot_response(self):
        try:
            respuesta = self._get_chatbot_response(self.body)
            if respuesta:
                self.env['whatsapp.message'].sudo().create({
                    'mobile_number': self.mobile_number,
                    'body': respuesta,
                    'state': 'outgoing',
                    'wa_account_id': self.wa_account_id.id if self.wa_account_id else None,
                    'create_uid': self.env.ref('base.user_admin').id  # o el ID de Sergio Ramello si querés
                })
        except Exception as e:
            _logger.error("Error al generar respuesta del chatbot: %s", e)

    def _get_chatbot_response(self, user_message):
        try:
            openai_api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not openai_api_key:
                _logger.error("La API key de OpenAI no está configurada")
                return _("Lo siento, hubo un problema al procesar tu mensaje.")
            openai.api_key = openai_api_key

            response = openai.ChatCompletion.create(
                model='gpt-3.5-turbo',
                messages=[
                    {"role": "system", "content": "Sos un asistente de WhatsApp dentro de Odoo. Respondé en español de forma breve y útil."},
                    {"role": "user", "content": user_message}
                ]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            _logger.error("Error al consultar OpenAI: %s", e)
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
