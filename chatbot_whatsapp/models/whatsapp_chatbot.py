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
    """Extrae nombre y correo si se menciona 'me llamo/soy/mi nombre es' y un email válido."""
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
    return any(g in text.lower() for g in greetings)

def has_product_keywords(text):
    """Verifica si el texto menciona palabras relacionadas a productos."""
    keywords = ("comprar", "producto", "oferta", "catálogo", "precio", "cera", "detergente", "pisos")
    return any(kw in text.lower() for kw in keywords)

# -----------------------------------------------------------
# RESPUESTAS FAQ (BASADAS EN REGLAS)
# -----------------------------------------------------------
FAQ_RESPONSES = {
    "horario": "Nuestros horarios de atención son: lunes a viernes de 8:30 a 12:30 y de 16:00 a 20:00, y sábados de 9:00 a 13:00.",
    "horarios": "Nuestros horarios de atención son: lunes a viernes de 8:30 a 12:30 y de 16:00 a 20:00, y sábados de 9:00 a 13:00.",
    "estado de cuenta": "Para ver tu estado de cuenta ingresa a www.quimicacristal.com, accede a tu cuenta y encontrarás el detalle de tus movimientos.",
    "que haces": "Soy el asistente virtual de Química Cristal. Estoy aquí para ayudarte a responder tus consultas sobre productos, horarios o información de cuenta.",
}

def check_faq(user_text):
    """Devuelve una respuesta predeterminada si la consulta coincide con alguna FAQ."""
    lower_text = user_text.lower()
    for key, answer in FAQ_RESPONSES.items():
        if key in lower_text:
            return answer
    return None

# -----------------------------------------------------------
# MODELO EXTENDIDO: WhatsAppMessage
# -----------------------------------------------------------
class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super(WhatsAppMessage, self).create(vals_list)
        for message in records:
            plain_body = clean_html(message.body)
            if message.state == 'received' and message.mobile_number and plain_body:
                _logger.info("Mensaje recibido (ID %s): %s", message.id, plain_body)

                # Primero, buscar respuestas FAQ
                faq_answer = check_faq(plain_body)
                if faq_answer:
                    response = faq_answer
                # Si es consulta de producto, intentar búsqueda en el catálogo
                elif has_product_keywords(plain_body):
                    response = self._handle_product_query(plain_body)
                    if not response:
                        # Si no se encontraron productos, se sigue con la respuesta conversacional
                        response = self._generate_chatbot_reply(plain_body)
                else:
                    response = self._generate_chatbot_reply(plain_body)

                # Evitar asignar valores nulos: forzamos respuesta como string
                response_text = str(response.strip()) if response and response.strip() else _("Lo siento, no pude procesar tu consulta en este momento.")
                _logger.info("Respuesta a enviar para el mensaje %s: %s", message.id, response_text)
                try:
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
                        _logger.info("Método _send_message no disponible; el mensaje quedará en cola.")
                except Exception as e:
                    _logger.error("Error al crear/enviar mensaje saliente para mensaje %s: %s", message.id, e)
                    
                # Actualiza datos de partner si es posible
                partner = self.env['res.partner'].sudo().search([('phone', '=', message.mobile_number)], limit=1)
                if partner:
                    data = extract_user_data(plain_body)
                    updates = {}
                    if data.get("name") and not partner.name:
                        updates["name"] = data["name"]
                    if data.get("email") and not partner.email:
                        updates["email"] = data["email"]
                    if updates:
                        _logger.info("Actualizando partner %s: %s", partner.id, updates)
                        partner.sudo().write(updates)
        return records

    def _handle_product_query(self, user_text):
        """Realiza una búsqueda en el catálogo y devuelve una respuesta formateada si se encuentran productos."""
        Product = self.env['product.template']
        domain = [('is_published', '=', True), '|', ('name', 'ilike', user_text), ('description_sale', 'ilike', user_text)]
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
                return (
                    "He encontrado los siguientes productos que podrían interesarte:\n\n" +
                    "\n".join(links) +
                    "\n\n¿Deseas información adicional sobre alguno?"
                )
        return None

    def _generate_chatbot_reply(self, user_text):
        """
        Genera una respuesta conversacional utilizando OpenAI, evitando saludos y promociones reiteradas.
        Se utiliza el contexto de los últimos 5 mensajes para dar una respuesta precisa y personalizada.
        """
        # Configuración de la API
        api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key') or environ.get('OPENAI_API_KEY')
        if not api_key:
            _logger.error("La API key de OpenAI no está configurada.")
            return _("Lo siento, no pude procesar tu mensaje.")
        openai.api_key = api_key

        # Construir el contexto (últimos 5 mensajes, orden ascendente)
        recent_msgs = self.env['whatsapp.message'].sudo().search([
            ('mobile_number', '=', self.mobile_number),
            ('id', '<', self.id),
            ('body', '!=', False)
        ], order='id desc', limit=5)
        context = []
        for msg in reversed(recent_msgs):
            role = 'user' if msg.state == 'received' else 'assistant'
            context.append({"role": role, "content": clean_html(msg.body)})
        context.append({"role": "user", "content": user_text})

        # Determinar si ya se saludó en mensajes anteriores para evitar repetir.
        already_greeted = False
        recent_outgoing = self.env['whatsapp.message'].sudo().search([
            ('mobile_number', '=', self.mobile_number),
            ('state', '=', 'outgoing')
        ], order='id desc', limit=1)
        if recent_outgoing and has_greeting(clean_html(recent_outgoing.body)):
            already_greeted = True

        # Sistema de prompt ajustado para evitar saludos y promoción reiterada:
        system_prompt = (
            "Eres el asistente virtual de atención al cliente de Química Cristal. Tu tarea es responder de forma precisa y profesional, "
            "centrándote en la consulta que realiza el usuario. Si el usuario formula una pregunta concreta o pide información específica, responde sin incluir saludos o menciones promocionales innecesarias. "
            "Solo saluda si es la primera interacción en la conversación o si el usuario inicia un saludo, y evita repetir la promoción en cada respuesta. "
            "En respuestas generales, mantén un tono cálido y cercano, pero sin reiterar ofertas promocionales de forma excesiva."
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
            # Si la respuesta inicia con un saludo y ya se saludó previamente, eliminar la línea del saludo.
            if has_greeting(reply_text) and already_greeted:
                lines = reply_text.splitlines()
                if len(lines) > 1:
                    reply_text = "\n".join(lines[1:]).strip()
            return reply_text
        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e, exc_info=True)
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
