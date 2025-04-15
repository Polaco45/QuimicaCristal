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
        Esta función genera la respuesta del chatbot de dos maneras:
         1. Si el mensaje del usuario contiene palabras clave definidas (por ejemplo, 'precio', 'cera', 'pisos', etc.),
            se buscarán productos publicados (is_published=True) en el catálogo (modelo product.template) filtrando
            por los términos encontrados en el mensaje. Si se encuentran productos, se arma un mensaje con enlaces completos.
         2. Si no se detecta que es una consulta de producto, se utiliza un contexto conversacional usando los
            últimos 5 mensajes para formular una respuesta cálida y personalizada. El sistema de prompt le indica
            al asistente que debe saludar de forma empática y preguntar el nombre del cliente si es un saludo.
        """
        # --- Parte 1: Búsqueda de productos ---
        product_keywords = ['comprar', 'producto', 'oferta', 'catálogo', 'venden', 'tienen', 'precio', 'cera', 'pisos']
        lower_msg = user_message.lower()
        if any(kw in lower_msg for kw in product_keywords):
            Product = self.env['product.template']
            # Se arma el dominio para buscar productos cuyo nombre o descripción contenga palabras clave del mensaje
            dominio = [('is_published', '=', True)]
            for word in user_message.split():
                word = word.strip().lower()
                if word:
                    # Se agrega condición OR para que coincida en name o description_sale
                    dominio += ['|', ('name', 'ilike', word), ('description_sale', 'ilike', word)]
            productos = Product.search(dominio, limit=10)
            if productos:
                links = []
                for prod in productos:
                    if prod.website_url:
                        # Asegurarse de que la URL tenga el prefijo https://
                        url = prod.website_url if prod.website_url.startswith("http") else "https://quimicacristal.com" + prod.website_url
                        links.append(f"🔹 {prod.name}: {url}")
                if links:
                    mensaje_productos = "¡Encontré los siguientes productos que podrían interesarte:\n" + "\n".join(links)
                    return mensaje_productos

        # --- Parte 2: Flujo conversacional con contexto ---
        # Configuración de la API Key: buscar en parámetros de configuración, sino en variable de entorno.
        api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
        if not api_key:
            api_key = environ.get('OPENAI_API_KEY')
        if not api_key:
            _logger.error("La API key de OpenAI no está configurada.")
            return _("Lo siento, no pude procesar tu mensaje.")
        openai.api_key = api_key

        # Recupera los últimos 5 mensajes de este número (excluyendo el actual)
        recent_messages = self.env['whatsapp.message'].sudo().search([
            ('mobile_number', '=', self.mobile_number),
            ('id', '<', self.id),
            ('body', '!=', False)
        ], order='id desc', limit=5)
        context_messages = []
        # Se ordenan cronológicamente de más antiguo a más reciente.
        for msg in reversed(recent_messages):
            role = 'user' if msg.state == 'received' else 'assistant'
            context_messages.append({"role": role, "content": msg.body})
        # Agregar el mensaje actual
        context_messages.append({"role": "user", "content": user_message})

        # Definir un prompt del sistema que distingue el caso de consumidor final:
        system_message = (
            "Eres un asistente de atención al cliente de Química Cristal, especializado en productos de limpieza para el hogar. "
            "Tu tarea es atender al cliente de forma cálida y amigable. Si recibes un saludo simple (por ejemplo, 'Hola'), "
            "responde preguntando su nombre, por ejemplo: '¡Hola! Gracias por comunicarte con Química Cristal. ¿Cómo te llamás?'. "
            "Si el mensaje es una consulta sobre productos, responde con información útil y, si corresponde, sin incluir precios, "
            "sino con enlaces directos a la sección o al producto en nuestro sitio web. "
            "Recuerda siempre tratar al cliente de manera cercana y profesional."
        )

        messages = [{"role": "system", "content": system_message}] + context_messages

        # Consultar a OpenAI
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
