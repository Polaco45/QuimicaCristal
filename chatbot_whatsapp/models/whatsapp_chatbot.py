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
                
                # Generamos la respuesta del chatbot
                chatbot_response = message._get_chatbot_response(message.body)
                _logger.info("Respuesta cruda del chatbot para mensaje %s: %s", message.id, chatbot_response)

                response_text = chatbot_response.strip() if chatbot_response and chatbot_response.strip() else _("Lo siento, no pude procesar tu consulta.")
                if not chatbot_response or not chatbot_response.strip():
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

    def _get_chatbot_response(self, user_message):
        """
        Responde al mensaje del usuario integrando:
         1. Búsqueda de productos publicados en el catálogo (name, description, description_sale).
         2. Si se encuentran, devuelve enlaces directos al sitio.
         3. Si no, utiliza el historial de conversación (últimos 5 mensajes) como contexto
            y llama a OpenAI con un base prompt que detalla el negocio, tono y preferencias.
        """
        # --- Sección 1: Buscar productos
        Product = self.env['product.template']
        palabras = user_message.lower().split()
        
        # Dominio base: productos publicados
        dominio = [('is_published', '=', True)]
        condiciones = []
        for palabra in palabras:
            condiciones += [
                ('name', 'ilike', palabra),
                ('description', 'ilike', palabra),
                ('description_sale', 'ilike', palabra),
            ]
        if condiciones:
            # Agregar operador OR entre condiciones (si hay más de una)
            if len(condiciones) > 1:
                dominio += ['|'] * (len(condiciones) - 1)
            dominio += condiciones

        productos = Product.search(dominio)
        if productos:
            links = [f"🔹 {p.name}: https://quimicacristal.com{p.website_url}" for p in productos if p.website_url]
            if links:
                return "¡Sí! Encontré estos productos relacionados:\n" + "\n".join(links)

        # --- Sección 2: Construir contexto conversacional

        # Obtener los últimos 5 mensajes del mismo número en orden ascendente (más antiguos primero)
        recent_messages = self.env['whatsapp.message'].sudo().search([
            ('mobile_number', '=', self.mobile_number),
            ('id', '<', self.id),
            ('body', '!=', False),
        ], order='id desc', limit=5)
        context_messages = []
        for msg in reversed(recent_messages):
            role = 'user' if msg.state == 'received' else 'assistant'
            context_messages.append({
                "role": role,
                "content": msg.body
            })
        # Incluir el mensaje actual
        context_messages.append({"role": "user", "content": user_message})

        # --- Sección 3: Definir el prompt base (system message)
        system_message = (
            "Sos un asistente de atención al cliente de Química Cristal, una empresa con amplia experiencia en la venta "
            "de productos de limpieza para el hogar e instituciones en Río Cuarto. "
            "Tu tono es profesional, amable y claro. Cuando respondas, si corresponde, proporciona enlaces directos "
            "al sitio web https://quimicacristal.com para que los clientes puedan ver los productos. "
            "No menciones precios, solo ayuda para encontrar el producto."
        )

        messages = [{"role": "system", "content": system_message}] + context_messages

        # --- Sección 4: Llamada a OpenAI
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.4,
                max_tokens=150,
            )
            _logger.info("Respuesta completa de OpenAI para el mensaje '%s': %s", user_message, response)
            try:
                return response.choices[0].message.content.strip()
            except Exception:
                return response.choices[0].message['content'].strip()
        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e, exc_info=True)
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
