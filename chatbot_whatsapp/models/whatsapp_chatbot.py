from odoo import models, api
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
                message.env['whatsapp.message'].create({
                    'mobile_number': message.mobile_number,
                    'body': chatbot_response,
                    'direction': 'outgoing',
                    'account_id': message.account_id.id,
                })
        return records

    def _get_chatbot_response(self, message_text):
        Product = self.env['product.template']
        palabras = message_text.lower().split()

        # Dominio base: productos publicados
        dominio = [('is_published', '=', True)]

        # Condiciones: coincidencias en name, description o description_sale
        condiciones = []
        for palabra in palabras:
            condiciones += [
                ('name', 'ilike', palabra),
                ('description', 'ilike', palabra),
                ('description_sale', 'ilike', palabra),
            ]

        if condiciones:
            if len(condiciones) > 1:
                dominio += ['|'] * (len(condiciones) - 1)
            dominio += condiciones

        productos = Product.search(dominio)

        if productos:
            links = [f"🔹 {p.name}: https://quimicacristal.com{p.website_url}" for p in productos if p.website_url]
            return "¡Sí! Encontré estos productos relacionados:\n" + "\n".join(links)

        try:
            respuesta = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Sos un asistente de atención al cliente de una tienda de limpieza llamada Química Cristal."},
                    {"role": "user", "content": message_text},
                ]
            )
            return respuesta['choices'][0]['message']['content']
        except Exception as e:
            _logger.error("Error al generar respuesta del chatbot: %s", e)
            return "¡Gracias por tu mensaje! Enseguida te respondemos."
