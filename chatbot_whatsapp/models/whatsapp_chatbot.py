from odoo import models, api, _
import openai
import logging
from os import environ

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
        Responde al mensaje del cliente de dos maneras:
         1. Si el mensaje contiene palabras clave (por ejemplo, 'comprar', 'producto', 'venden', etc.), busca en el catálogo
            productos publicados (is_published=True) y devuelve enlaces a los productos.
         2. Si no se detectan consultas sobre productos, utiliza los últimos 5 mensajes para armar el contexto conversacional.
            Usa un prompt del sistema que indica que debes tratar al cliente de forma cálida y natural, y en caso de ser un saludo,
            deberás responder saludando y preguntando por su nombre.
        """
        # Sección 1: Búsqueda de productos si se detectan palabras clave
        product_keywords = ['comprar', 'producto', 'oferta', 'catálogo', 'venden', 'tienen']
        if any(kw in user_message.lower() for kw in product_keywords):
            Product = self.env['product.template']
            # Construir el dominio para buscar productos publicados cuyo nombre o descripción contenga algunas palabras del mensaje
            dominio = [('is_published', '=', True)]
            for word in user_message.split():
                dominio += ['|', ('name', 'ilike', word), ('description_sale', 'ilike', word)]
            productos = Product.search(dominio, limit=10)
            if productos:
                links = [f"🔹 {prod.name}: https://quimicacristal.com{prod.website_url}" for prod in productos if prod.website_url]
                mensaje = "¡Encontré estos productos para vos:\n" + "\n".join(links)
                return mensaje

        # Sección 2: Preparar API key
        api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
        if not api_key:
            api_key = environ.get('OPENAI_API_KEY')
        if not api_key:
            _logger.error("La API key de OpenAI no está configurada.")
            return _("Lo siento, no pude procesar tu mensaje.")
        openai.api_key = api_key

        # Sección 3: Crear contexto conversacional usando los últimos 5 mensajes
        recent_messages = self.env['whatsapp.message'].sudo().search([
            ('mobile_number', '=', self.mobile_number),
            ('id', '<', self.id),
            ('body', '!=', False)
        ], order='id desc', limit=5)
        context_messages = []
        for msg in reversed(recent_messages):
            role = 'user' if msg.state == 'received' else 'assistant'
            context_messages.append({"role": role, "content": msg.body})
        context_messages.append({"role": "user", "content": user_message})
        
        # Sección 4: Definir un prompt del sistema personalizado para los consumidores
        system_message = (
            "Eres un asistente de atención al cliente de Química Cristal, una empresa especializada en productos de limpieza para el hogar. "
            "Tu comunicación debe ser cálida, empática y cercana. Si recibes un saludo, responde de forma amigable y pregunta el nombre del cliente, "
            "por ejemplo: '¡Hola! Gracias por comunicarte con Química Cristal. ¿Cómo te llamás?'. "
            "Si el mensaje es una consulta sobre productos, responde con enlaces directos a los productos (sin precios) y sin mencionar información de precios."
        )
        messages = [{"role": "system", "content": system_message}] + context_messages

        # Sección 5: Consultar a OpenAI
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
