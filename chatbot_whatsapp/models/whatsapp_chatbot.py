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
            # Procesa solo mensajes recibidos con número y contenido
            if message.state == 'received' and message.mobile_number and message.body:
                _logger.info("Mensaje recibido (ID %s): %s", message.id, message.body)
                response = message._get_chatbot_response(message.body)
                _logger.info("Respuesta cruda para mensaje %s: %s", message.id, response)

                response_text = response.strip() if response and response.strip() else _("Lo siento, no pude procesar tu consulta.")
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
                    _logger.info("Mensaje saliente creado: ID %s, body = %s", outgoing_msg.id, outgoing_msg.body)
                    if hasattr(outgoing_msg, '_send_message'):
                        outgoing_msg._send_message()
                    else:
                        _logger.info("No se encontró _send_message; el mensaje quedará en cola.")
                except Exception as e:
                    _logger.error("Error al crear/enviar mensaje saliente para registro %s: %s", message.id, e)
        return records

    def _get_chatbot_response(self, user_message):
        """
        Genera la respuesta del chatbot de dos maneras:

        1. Si el mensaje contiene términos que indican una consulta de producto
           (por ejemplo, 'cera', 'detergente', 'precio', etc.), se realiza una búsqueda
           en el catálogo (modelo 'product.template'). Se filtran productos publicados y se
           comparan sus campos 'name' y 'description_sale' con el mensaje del usuario.
           Si se encuentran resultados, se arma una respuesta con una lista de enlaces bien
           formateados a cada producto.

        2. Si no es una consulta de productos, se emplea la API de OpenAI utilizando el
           contexto de los últimos mensajes para generar una respuesta conversacional y
           empática. El prompt del sistema le indica al asistente que actúe como un agente
           de atención al cliente.
        """
        # --- Parte 1: Consulta de productos ---
        product_keywords = ['comprar', 'producto', 'oferta', 'catálogo', 'venden', 'tienen', 'precio', 'cera', 'detergente', 'pisos']
        lower_msg = user_message.lower()
        if any(kw in lower_msg for kw in product_keywords):
            Product = self.env['product.template']
            # Se utiliza el mensaje completo para la búsqueda
            domain = [
                ('is_published', '=', True),
                '|', ('name', 'ilike', user_message),
                    ('description_sale', 'ilike', user_message)
            ]
            productos = Product.search(domain, limit=10)
            if productos:
                links = []
                for prod in productos:
                    # Se usa el campo website_url; si no comienza con http, se le agrega el prefijo
                    if prod.website_url:
                        url = prod.website_url if prod.website_url.startswith("http") else "https://quimicacristal.com" + prod.website_url
                    else:
                        # Si no existe website_url, se genera un enlace genérico basado en el ID del producto
                        url = f"https://quimicacristal.com/shop/product/{prod.id}"
                    links.append(f"🔹 {prod.name} – {url}")
                if links:
                    mensaje_productos = ("¡He encontrado los siguientes productos que pueden interesarte:\n\n" +
                                          "\n".join(links) +
                                          "\n\n¿Deseas información adicional sobre alguno en particular?")
                    return mensaje_productos
                # Si no se encuentran productos, continúa con el flujo conversacional.

        # --- Parte 2: Conversación empática y contextualizada ---
        # Configuración de la API key: buscar en parámetros o en la variable de entorno.
        api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key') or environ.get('OPENAI_API_KEY')
        if not api_key:
            _logger.error("La API key de OpenAI no está configurada.")
            return _("Lo siento, no pude procesar tu mensaje.")
        openai.api_key = api_key

        # Recupera los últimos 5 mensajes (excluyendo el actual) para darle contexto a la conversación.
        recent_messages = self.env['whatsapp.message'].sudo().search([
            ('mobile_number', '=', self.mobile_number),
            ('id', '<', self.id),
            ('body', '!=', False)
        ], order='id desc', limit=5)
        context_messages = []
        # Ordenar de más antiguo a más reciente
        for msg in reversed(recent_messages):
            role = 'user' if msg.state == 'received' else 'assistant'
            context_messages.append({"role": role, "content": msg.body})
        # Agregar el mensaje actual
        context_messages.append({"role": "user", "content": user_message})

        # Definir el prompt del sistema para atención al cliente
        system_message = (
            "Eres un asistente de atención al cliente de Química Cristal especializado en productos de limpieza para el hogar. "
            "Responde de forma cálida y cercana. Si recibes un saludo (por ejemplo, 'Hola'), debes responder preguntando el nombre del cliente. "
            "En consultas generales, utiliza el contexto de los mensajes anteriores para ofrecer una respuesta personalizada y profesional."
        )

        messages = [{"role": "system", "content": system_message}] + context_messages

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
