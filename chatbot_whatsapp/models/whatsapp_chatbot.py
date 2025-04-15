# -*- coding: utf-8 -*-
from odoo import models, api, _
import openai
import logging
from os import environ

_logger = logging.getLogger(__name__)


class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    # ------------------------------------------------------------------
    # CREACIÓN DEL MENSAJE ENTRANTE
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super(WhatsAppMessage, self).create(vals_list)
        for message in records:
            # Procesa solo mensajes recibidos con número y contenido
            if message.state == 'received' and message.mobile_number and message.body:
                _logger.info("Mensaje recibido (ID %s): %s", message.id, message.body)

                response = message._get_chatbot_response(message.body)
                _logger.info("Respuesta cruda para mensaje %s: %s", message.id, response)

                response_text = response.strip() if response and response.strip() else _(
                    "Lo siento, no pude procesar tu consulta."
                )
                if not response or not response.strip():
                    _logger.warning("La respuesta quedó vacía para el mensaje %s", message.id)

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
                    _logger.info(
                        "Mensaje saliente creado: ID %s, body = %s",
                        outgoing_msg.id,
                        outgoing_msg.body,
                    )
                    if hasattr(outgoing_msg, '_send_message'):
                        outgoing_msg._send_message()
                    else:
                        _logger.info("No se encontró _send_message; el mensaje quedará en cola.")
                except Exception as e:
                    _logger.error(
                        "Error al crear/enviar mensaje saliente para registro %s: %s",
                        message.id,
                        e,
                    )
        return records

    # ------------------------------------------------------------------
    # GENERA RESPUESTA
    # ------------------------------------------------------------------
    def _get_chatbot_response(self, user_message):
        """
        1) Si detecta palabras de producto/precio, devuelve lista de enlaces.
        2) Si no, llama a OpenAI con contexto conversacional y prompt.
        """
        # --- Parte 1 : búsqueda de productos ---------------------------
        product_keywords = [
            'comprar', 'producto', 'oferta', 'catálogo', 'venden', 'tienen',
            'precio', 'cera', 'detergente', 'pisos',
        ]
        lower_msg = user_message.lower()
        if any(kw in lower_msg for kw in product_keywords):
            Product = self.env['product.template']
            domain = [
                ('is_published', '=', True),
                '|', ('name', 'ilike', user_message),
                     ('description_sale', 'ilike', user_message),
            ]
            productos = Product.search(domain, limit=10)
            if productos:
                links = []
                for prod in productos:
                    if prod.website_url:
                        url = (
                            prod.website_url
                            if prod.website_url.startswith("http")
                            else "https://quimicacristal.com" + prod.website_url
                        )
                    else:
                        url = f"https://quimicacristal.com/shop/product/{prod.id}"
                    links.append(f"🔹 {prod.name} – {url}")
                if links:
                    return (
                        "¡He encontrado los siguientes productos que pueden interesarte:\n\n"
                        + "\n".join(links)
                        + "\n\n¿Deseas información adicional sobre alguno en particular?"
                    )
            # si no hay resultados, continúa al flujo conversacional

        # --- Parte 2 : conversación empática ---------------------------
        api_key = (
            self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            or environ.get('OPENAI_API_KEY')
        )
        if not api_key:
            _logger.error("La API key de OpenAI no está configurada.")
            return _("Lo siento, no pude procesar tu mensaje.")
        openai.api_key = api_key

        recent_messages = self.env['whatsapp.message'].sudo().search(
            [
                ('mobile_number', '=', self.mobile_number),
                ('id', '<', self.id),
                ('body', '!=', False),
            ],
            order='id desc',
            limit=5,
        )
        context_messages = []
        for msg in reversed(recent_messages):
            role = 'user' if msg.state == 'received' else 'assistant'
            context_messages.append({"role": role, "content": msg.body})
        context_messages.append({"role": "user", "content": user_message})

        # --- PROMPT POTENCIADO -----------------------------------------
        system_message = (
            "Eres el *chatbot oficial* de **Química Cristal**. Tu personalidad es amigable, cercana, divertida y "
            "persuasiva.\n\n"
            "⚙️  **Reglas principales**\n"
            "1. Saluda *solo* si el usuario te saluda; no repitas saludos.\n"
            "2. Si aún no conoces nombre y correo del cliente, pídeselos con calidez cuando sea oportuno.\n"
            "3. Para dudas de precios, stock o compras, redirige SIEMPRE al sitio 👉 www.quimicacristal.com.\n"
            "4. Recuerda mencionar que el **envío es gratis** en compras superiores a **$30 000**.\n"
            "5. Cierra cada respuesta destacando la **promoción del mes** e invitando a comprar.\n"
            "6. Si la consulta está fuera de alcance, sugiere visitar la web o escribir al WhatsApp 358 548 1199.\n\n"
            "🕒  **Horarios de atención**\n"
            "• Lunes a viernes: 8:30 – 12:30 y 16:00 – 20:00\n"
            "• Sábados: 9:00 – 13:00\n\n"
            "Habla siempre con entusiasmo, usa emojis con moderación 😊🎉 y mantén respuestas breves, claras y "
            "orientadas a la acción."
        )

        messages = [{"role": "system", "content": system_message}] + context_messages

        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.4,
                max_tokens=150,
            )
            _logger.info(
                "Respuesta completa de OpenAI para el mensaje '%s': %s",
                user_message,
                response,
            )
            try:
                return response.choices[0].message.content.strip()
            except Exception:
                return response.choices[0].message['content'].strip()
        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e, exc_info=True)
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
