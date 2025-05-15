# -*- coding: utf-8 -*-
import openai
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class WhatsappMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create to:
        1) Read the WhatsApp account fields directly
           (access_token, phone_number_id, and openai_api_key).
        2) Assign them into each whatsapp.message before creation.
        3) After creating the record(s), generate and send a chatbot reply.
        """
        for vals in vals_list:
            # 1) Get the account record
            acct = self.env['whatsapp.account'].browse(vals.get('whatsapp_account_id'))
            if not acct:
                raise UserError(_("No hay ninguna cuenta de WhatsApp configurada."))

            # 2) Read the credentials from the account record
            access_token = acct.access_token
            phone_number_id = acct.phone_number_id
            openai_api_key = acct.openai_api_key

            if not access_token or not phone_number_id:
                raise UserError(_("Credenciales de WhatsApp no configuradas en la cuenta."))
            if not openai_api_key:
                raise UserError(_("Clave de OpenAI no configurada en la cuenta."))

            # 3) Configure OpenAI
            openai.api_key = openai_api_key

            # 4) Inject into vals so the base create() sees them
            vals.update({
                'access_token': access_token,
                'phone_number_id': phone_number_id,
            })

        # 5) Call the original create()
        records = super(WhatsappMessage, self).create(vals_list)

        # 6) For each newly created message, generate & send a reply
        for rec in records:
            user_text = rec.body or ''
            if user_text.strip():
                # Generate reply via OpenAI
                reply_text = rec._generate_chatbot_reply(user_text)
                # Send it back over WhatsApp
                rec.send_whatsapp_message(reply_text)

        return records

    def _generate_chatbot_reply(self, user_text):
        """
        Llama a la API de OpenAI y devuelve la respuesta del asistente como texto plano.
        """
        self.ensure_one()

        prompt = f"""Sos un asesor de ventas por WhatsApp de una empresa de productos de limpieza.
Tu tarea es responder de forma amable, clara y profesional.
Respondé solo consultas relacionadas con productos de limpieza, promociones o ventas.
Si no entendés algo, pedí que reformulen la pregunta.
Nunca repitas saludos ni nombres.
Este es el mensaje del cliente:\n\n{user_text.strip()}
"""

        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=500,
            )
            return response.choices[0].message['content'].strip()

        except Exception as e:
            raise UserError(f"Error al generar la respuesta del chatbot: {str(e)}")
