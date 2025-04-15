# -*- coding: utf-8 -*-
from odoo import models, api, _
import openai
import logging
import re
from os import environ

_logger = logging.getLogger(__name__)


class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    # ---------------------------------------------------------------------
    # CREACIÓN DEL MENSAJE ENTRANTE
    # ---------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)

        for message in records:
            # Procesar solo los mensajes entrantes con cuerpo y número
            if (
                message.state == 'received'
                and message.mobile_number
                and message.body
            ):
                _logger.info("Mensaje recibido (ID %s): %s", message.id, message.body)

                # 1) Generar respuesta
                response = message._get_chatbot_response(message.body)

                # 2) Garantizar que nunca sea vacío
                response_text = (response or "").strip()
                if not response_text:
                    response_text = _(
                        "Lo siento, no pude procesar tu consulta. "
                        "Podés visitar www.quimicacristal.com o escribirnos nuevamente 😊."
                    )

                _logger.info("Mensaje a enviar por WhatsApp: %s", response_text)

                # 3) Crear y enviar mensaje saliente
                try:
                    outgoing_msg = self.env['whatsapp.message'].sudo().create({
                        'mobile_number': message.mobile_number,
                        'body': response_text,
                        'state': 'outgoing',
                        'create_uid': self.env.ref('base.user_admin').id,
                        'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
                    })
                    outgoing_msg._send_message()
                except Exception as e:
                    _logger.error("Error al enviar mensaje saliente: %s", e)

                # 4) Extraer y guardar nombre / correo en el contacto
                user_data = self._extract_user_data(message.body)
                partner = self.env['res.partner'].sudo().search(
                    [('phone', '=', message.mobile_number)], limit=1
                )
                if partner:
                    updates = {}
                    if user_data['name'] and not partner.name:
                        updates['name'] = user_data['name']
                    if user_data['email'] and not partner.email:
                        updates['email'] = user_data['email']
                    if updates:
                        _logger.info("Actualizando datos del cliente %s: %s", partner.id, updates)
                        partner.sudo().write(updates)

        return records

    # ---------------------------------------------------------------------
    # EXTRACCIÓN DE DATOS DEL MENSAJE
    # ---------------------------------------------------------------------
    def _extract_user_data(self, text):
        name_pattern = r'(?:me llamo|soy|mi nombre es)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+)*)'
        email_pattern = r'[\w\.\-]+@(?:gmail|hotmail|yahoo|outlook|icloud)\.(?:com|ar)'

        name_match = re.search(name_pattern, text, re.IGNORECASE)
        email_match = re.search(email_pattern, text)

        return {
            'name': name_match.group(1).strip() if name_match else None,
            'email': email_match.group(0) if email_match else None,
        }

    # ---------------------------------------------------------------------
    # GENERADOR DE RESPUESTA CON OPENAI
    # ---------------------------------------------------------------------
    def _get_chatbot_response(self, user_message):
        # API‑KEY
        api_key = (
            self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            or environ.get('OPENAI_API_KEY')
        )
        if not api_key:
            _logger.error("API Key de OpenAI no configurada.")
            return None
        openai.api_key = api_key

        lower_msg = user_message.lower()

        # 1) Detectar saludo
        saludo_detectado = any(
            kw in lower_msg
            for kw in ['hola', 'buenas', 'buen día', 'buenas tardes', 'buenas noches', 'qué tal']
        )

        # 2) Detectar interés en productos/precios
        product_keywords = [
            'precio', 'comprar', 'producto', 'catálogo',
            'cera', 'detergente', 'lavandina', 'limpiador', 'pisos'
        ]
        if any(kw in lower_msg for kw in product_keywords):
            return (
                "Tenemos muchos productos que pueden interesarte 😄.\n"
                "Consultá el catálogo completo y hacé tu pedido en 👉 www.quimicacristal.com\n\n"
                "📦 Envío gratis en compras desde $30.000.\n"
                "¡Aprovechá nuestra promo del mes! 🎉"
            )

        # 3) Recuperar contexto (últimos 3 mensajes)
        recent = self.env['whatsapp.message'].sudo().search(
            [
                ('mobile_number', '=', self.mobile_number),
                ('id', '<', self.id),
                ('body', '!=', False),
            ],
            order='id desc',
            limit=3,
        )
        history = [
            {"role": 'user' if m.state == 'received' else 'assistant', "content": m.body}
            for m in reversed(recent)
        ]
        history.append({"role": "user", "content": user_message})

        # 4) Prompt del sistema
        system_msg = (
            "Eres el asistente virtual de Química Cristal. "
            "Tu estilo es cálido, cercano, divertido y persuasivo. "
            "Saluda solo si el usuario inicia con un saludo. "
            "Si no puedes responder, indica que visite www.quimicacristal.com "
            "o escriba al WhatsApp 3585481199.\n"
            "Recordá mencionar el envío gratis desde $30.000 y las promociones vigentes."
        )

        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "system", "content": system_msg}] + history,
                temperature=0.5,
                max_tokens=200,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            _logger.error("Error con OpenAI: %s", e, exc_info=True)
            return _(
                "Tuvimos un problema técnico 🙈. "
                "Podés ingresar a www.quimicacristal.com o escribir al WhatsApp 3585481199."
            )
