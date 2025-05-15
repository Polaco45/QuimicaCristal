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
        Entrypoint to call OpenAI's ChatCompletion API.
        Returns the assistant's reply as a string.
        """
        self.ensure_one()
        # Build the messages payload; you can extend this with system or context messages
        messages = [
            {"role": "user", "content": user_text}
        ]
        # Call the OpenAI API
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.7,
            max_tokens=150,
        )
        # Extract and return the assistant's reply
        return response.choices[0].message.content.strip()
