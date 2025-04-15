# -*- coding: utf-8 -*-
from odoo import models, api, _
import openai
import logging
import re
from os import environ

_logger = logging.getLogger(__name__)

# -----------------------------------------------------------
# UTILIDADES
# -----------------------------------------------------------
HTML_TAGS = re.compile(r"<[^>]+>")

def clean_html(text):
    """Elimina etiquetas HTML y espacios sobrantes."""
    return re.sub(HTML_TAGS, "", text or "").strip()

def extract_user_data(text):
    """Extrae nombre y correo del texto si se menciona 'me llamo/soy/mi nombre es' y un email válido."""
    name_pat = r"(?:me llamo|soy|mi nombre es)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+)*)"
    email_pat = r"[\w\.\-]+@(?:gmail|hotmail|yahoo|outlook|icloud)\.(?:com|ar)"
    name_match = re.search(name_pat, text, re.IGNORECASE)
    email_match = re.search(email_pat, text)
    return {
        "name": name_match.group(1).strip() if name_match else None,
        "email": email_match.group(0) if email_match else None,
    }

def has_greeting(text):
    """Determina si el texto contiene un saludo común."""
    greetings = ("hola", "buenos días", "buenas tardes", "buenas noches", "qué tal")
    text_lower = text.lower()
    return any(g in text_lower for g in greetings)

def has_product_keywords(text):
    """Determina si el texto contiene palabras clave relacionadas con productos."""
    keywords = ("comprar", "producto", "oferta", "catálogo", "precio", "cera", "detergente", "pisos")
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)

# -----------------------------------------------------------
# MODELO EXTENDIDO: WhatsAppMessage
# -----------------------------------------------------------
class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super(WhatsAppMessage, self).create(vals_list)
        for message in records:
            # Procesar mensajes recibidos con número y contenido no vacío (limpio)
            plain_body = clean_html(message.body)
            if message.state == 'received' and message.mobile_number and plain_body:
                _logger.info("Mensaje recibido (ID %s): %s", message.id, plain_body)
                
                # Generar respuesta vía nuestro chatbot
                response = message._generate_chatbot_reply(plain_body)
                response_text = response.strip() if response and response.strip() else _(
                    "Lo siento, no pude procesar tu consulta. Por favor, visita www.quimicacristal.com o contacta al WhatsApp 3585481199."
                )
                
                _logger.info("Respuesta a enviar para el mensaje %s: %s", message.id, response_text)
                
                try:
                    # Asegurarse de que 'body' siempre contenga texto
                    outgoing_vals = {
                        'mobile_number': message.mobile_number,
                        'body': response_text,
                        'state': 'outgoing',
                        'create_uid': self.env.ref('base.user_admin').id,
                        'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
                    }
                    outgoing_msg = self.env['whatsapp.message'].sudo().create(outgoing_vals)
                    _logger.info("Mensaje saliente creado: ID %s, body: %s", outgoing_msg.id, outgoing_msg.body)
                    if hasattr(outgoing_msg, '_send_message'):
                        outgoing_msg._send_message()
                    else:
                        _logger.info("No se encontró _send_message; el mensaje quedará en cola.")
                except Exception as e:
                    _logger.error("Error al crear/enviar mensaje saliente para mensaje %s: %s", message.id, e)
                
                # Actualizar datos del partner si se detectan nombre y correo
                partner = self.env['res.partner'].sudo().search(
                    [('phone', '=', message.mobile_number)],
                    limit=1
                )
                if partner:
                    data = extract_user_data(plain_body)
                    updates = {}
                    if data.get("name") and not partner.name:
                        updates["name"] = data["name"]
                    if data.get("email") and not partner.email:
                        updates["email"] = data["email"]
                    if updates:
                        _logger.info("Actualizando datos del partner %s: %s", partner.id, updates)
                        partner.sudo().write(updates)
        return records

    def _generate_chatbot_reply(self, user_text):
        """
        Genera la respuesta del chatbot de dos maneras:
        
        1. Si el mensaje contiene palabras clave de producto, se busca en el catálogo y se devuelven enlaces de interés.
        2. Si no es una consulta de producto, se utiliza la API de OpenAI para generar una respuesta conversacional
           aprovechando el contexto de los últimos mensajes. El prompt del sistema está diseñado para ser
           empático, profesional y evitar saludos repetitivos.
        """
        # PARTE 1: Consulta de productos
        if has_product_keywords(user_text):
            Product = self.env['product.template']
            domain = [
                ('is_published', '=', True),
                '|',
                    ('name', 'ilike', user_text),
                    ('description_sale', 'ilike', user_text)
            ]
            productos = Product.search(domain, limit=10)
            if productos:
                links = []
                for prod in productos:
                    if prod.website_url:
                        url = prod.website_url if prod.website_url.startswith("http") else "https://quimicacristal.com" + prod.website_url
                    else:
                        url = "https://quimicacristal.com/shop/product/%s" % prod.id
                    links.append(f"🔹 {prod.name} – {url}")
                if links:
                    mensaje_productos = (
                        "¡He encontrado los siguientes productos que pueden interesarte:\n\n" +
                        "\n".join(links) +
                        "\n\n¿Deseas recibir más información sobre alguno en particular?"
                    )
                    return mensaje_productos
            # Si no se encuentran productos, continúa con el flujo conversacional.

        # PARTE 2: Conversación utilizando OpenAI
        api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key') or environ.get('OPENAI_API_KEY')
        if not api_key:
            _logger.error("La API key de OpenAI no está configurada.")
            return _("Lo siento, no pude procesar tu mensaje.")
        openai.api_key = api_key

        # Construir el contexto de la conversación con los últimos 5 mensajes (orden ascendente)
        recent_messages = self.env['whatsapp.message'].sudo().search([
            ('mobile_number', '=', self.mobile_number),
            ('id', '<', self.id),
            ('body', '!=', False)
        ], order='id desc', limit=5)

        context = []
        for msg in reversed(recent_messages):
            role = 'user' if msg.state == 'received' else 'assistant'
            context.append({"role": role, "content": clean_html(msg.body)})
        context.append({"role": "user", "content": user_text})

        # Evitar saludos repetidos: si el último mensaje enviado ya contenía un saludo, se omite
        already_greeted = False
        recent_outgoing = self.env['whatsapp.message'].sudo().search([
            ('mobile_number', '=', self.mobile_number),
            ('state', '=', 'outgoing')
        ], order='id desc', limit=1)
        if recent_outgoing:
            last_outgoing = clean_html(recent_outgoing.body)
            if has_greeting(last_outgoing):
                already_greeted = True

        # Prompt del sistema mejorado
        system_prompt = (
            "Eres el asistente virtual de atención al cliente de Química Cristal. "
            "Tu tono es cálido, cercano, divertido y profesional. "
            "Responde de forma empática y concisa, utilizando el contexto previo de la conversación. "
            "Si el usuario te saluda y aún no has saludado, contesta con un cordial saludo y pregunta su nombre de manera natural; "
            "de lo contrario, evita repetir saludos innecesariamente. "
            "Si no dispones de la información, invita al usuario a visitar www.quimicacristal.com o a contactar al WhatsApp 3585481199. "
            "Recuerda destacar la promoción de envío gratis en compras desde $30.000 y las ofertas vigentes."
        )

        messages = [{"role": "system", "content": system_prompt}] + context

        try:
            reply_result = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.45,
                max_tokens=200,
            )
            _logger.info("Respuesta completa de OpenAI: %s", reply_result)
            reply_text = reply_result.choices[0].message.content.strip()
            # Si la respuesta incluye un saludo pero ya se había saludado, quitar la primera línea.
            if has_greeting(reply_text) and (not has_greeting(user_text) or already_greeted):
                lines = reply_text.splitlines()
                if len(lines) > 1:
                    reply_text = "\n".join(lines[1:]).strip()
            return reply_text
        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e, exc_info=True)
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
