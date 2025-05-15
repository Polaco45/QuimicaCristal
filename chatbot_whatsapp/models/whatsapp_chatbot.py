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

def normalize_phone(phone):
    """
    Normaliza un número de teléfono extrayendo solo dígitos y
    eliminando prefijos internacionales: si comienza con "549", se remueven los 3 primeros dígitos;
    si comienza con "54", se remueven los 2 primeros.
    """
    phone_norm = phone.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if phone_norm.startswith('549'):
        phone_norm = phone_norm[3:]
    elif phone_norm.startswith('54'):
        phone_norm = phone_norm[2:]
    return phone_norm

def extract_user_data(text):
    """
    Extrae nombre y correo a partir de frases como "me llamo", "soy" o "mi nombre es"
    y un email válido.
    """
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
    """Verifica si el texto contiene palabras comunes relacionadas a productos."""
    keywords = ("comprar", "producto", "oferta", "catálogo", "precio", "jabón", "cera", "detergente", "pisos")
    return any(kw in text.lower() for kw in keywords)

def is_valid_product_query(user_text):
    """
    Verifica que la consulta se refiera a un producto dentro de nuestro dominio,
    utilizando la siguiente lista de palabras permitidas (categorías).
    """
    allowed_keywords = [
        "combos", "ofertas",
        "líquidos de limpieza", "lavandinas", "detergentes", "limpiadores desodorantes",
        "desengrasantes", "desinfectantes", "insecticida", "mantenimiento de pisos", "químicos para piletas", "higiene personal",
        "lampazos", "mopas", "pasaceras", "articulos de limpieza", "alfombras", "felpudos",
        "baldes", "fuentones", "barrenderos", "mopas institucionales", "limpiavidrios", "bazar",
        "gatillos", "pulverizadores", "plumeros", "guantes", "secadores", "sopapas",
        "bolsas", "trapos", "gamuzas", "repasadores", "palas", "cestos", "contenedores",
        "casa y jardin", "escobillones", "cepillos",
        "piscina", "cloro granulado", "pastillas", "químicos para pileta", "accesorios para piletas",
        "cuidado del automotor", "líquidos", "aromatizantes", "accesorios",
        "papel", "papel higienico", "rollos de cocina", "toallas intercaladas", "bobinas",
        "aerosoles aromatizantes", "sahumerios", "difusores", "aceites esenciales", "perfumes textiles",
        "residuos", "cuidado de la ropa", "jabones y suavizantes", "otros", "cabos",
        "consumo masivo", "dispensers", "químicos para tu pileta", "boyas", "accesorios y mantenimiento", "barrefondos", "sacabichos"
    ]
    text_lower = user_text.lower()
    for kw in allowed_keywords:
        if kw in text_lower:
            return True
    return False

def is_obscene_query(user_text):
    """
    Detecta si la consulta contiene términos obscenos o fuera de nuestro dominio.
    Ejemplos: "dildo", "dildos", "pene de goma", "penes de goma".
    """
    obscene_terms = ["dildo", "dildos", "pene de goma", "penes de goma"]
    text_lower = user_text.lower()
    for term in obscene_terms:
        if term in text_lower:
            return True
    return False

# -----------------------------------------------------------
# RESPUESTAS FAQ (BASADAS EN REGLAS)
# -----------------------------------------------------------
FAQ_RESPONSES = {
    "horario": ("Nuestros horarios de atención son: lunes a viernes de 8:30 a 12:30 y de 16:00 a 20:00, "
                "y sábados de 9:00 a 13:00. Además, nos encuentras en San Martin 2350, Río Cuarto, Córdoba. "
                "Visita www.quimicacristal.com para más detalles. 😊"),
    "horarios": ("Nuestros horarios de atención son: lunes a viernes de 8:30 a 12:30 y de 16:00 a 20:00, "
                 "y sábados de 9:00 a 13:00. Además, nos encontramos en San Martin 2350, Río Cuarto, Córdoba. "
                 "Ingresa a www.quimicacristal.com para más info. 😊"),
    "estado de cuenta": "Para ver tu estado de cuenta, ingresa a www.quimicacristal.com y accede a tu cuenta. 💻",
    "que haces": "Soy tu asistente de Química Cristal y estoy aquí para ayudarte con consultas sobre productos, horarios o información de cuenta. 🤖",
    "local": ("Nuestro local está en San Martin 2350, Río Cuarto, Córdoba (Química Cristal). "
              "Nuestro horario es de lunes a viernes de 8:30 a 12:30 y de 16:00 a 20:00, y sábados de 9:00 a 13:00. "
              "Visita www.quimicacristal.com para más info. 📍"),
    "dirección": ("Nuestra dirección es San Martin 2350, Río Cuarto, Córdoba (Química Cristal). "
                  "Consulta www.quimicacristal.com para más detalles. 📍"),
    "ubicación": ("Nos encontramos en San Martin 2350, Río Cuarto, Córdoba (Química Cristal). "
                  "Horario: lunes a viernes 8:30–12:30 y 16:00–20:00, sábados 9:00–13:00. Más info en www.quimicacristal.com. 📍"),
    "ubicacion": ("Nos encontramos en San Martin 2350, Río Cuarto, Córdoba (Química Cristal). "
                  "Horario: lunes a viernes 8:30–12:30 y 16:00–20:00, sábados 9:00–13:00. Más info en www.quimicacristal.com. 📍"),
    "ubicados": ("Nos encontramos en San Martin 2350, Río Cuarto, Córdoba (Química Cristal). "
                 "Nuestro horario es de lunes a viernes de 8:30 a 12:30 y de 16:00 a 20:00, y sábados de 9:00 a 13:00. "
                 "Visita www.quimicacristal.com para más info. 📍"),
    "ubix": ("Nos encontramos en San Martin 2350, Río Cuarto, Córdoba (Química Cristal). "
             "Horario: lunes a viernes 8:30–12:30 y 16:00–20:00, sábados 9:00–13:00. Más info en www.quimicacristal.com. 📍"),
    "ubixando": ("Nos encontramos en San Martin 2350, Río Cuarto, Córdoba (Química Cristal). "
                 "Nuestro horario es de lunes a viernes de 8:30 a 12:30 y de 16:00 a 20:00, y sábados de 9:00 a 13:00. "
                 "Visita www.quimicacristal.com para más info. 📍")
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
                normalized_phone = normalize_phone(message.mobile_number)
                
                # Buscar en res.partner usando "ilike" en campos phone o mobile
                partner = self.env['res.partner'].sudo().search([
                    '|',
                    ('phone', 'ilike', normalized_phone),
                    ('mobile', 'ilike', normalized_phone)
                ], limit=1)
                
                # Si la consulta es obscena, responder de forma predeterminada
                if is_obscene_query(plain_body):
                    response = ("Lo siento, en Química Cristal Minorista nos especializamos en la venta de insumos de limpieza para el hogar. "
                                "Te invito a ver nuestro catálogo en www.quimicacristal.com para conocer nuestros productos.")
                else:
                    faq_answer = check_faq(plain_body)
                    if faq_answer:
                        response = faq_answer
                    elif has_product_keywords(plain_body):
                        if is_valid_product_query(plain_body):
                            response = self._handle_product_query(plain_body)
                        else:
                            response = ("Lo siento, en Química Cristal Minorista nos especializamos en insumos de limpieza y cuidado del hogar. "
                                        "Te invito a ver nuestro catálogo en www.quimicacristal.com para conocer lo que ofrecemos. 😉")
                    else:
                        response = self._generate_chatbot_reply(plain_body)
                        
                response_text = str(response.strip()) if response and response.strip() else _("Lo siento, no pude procesar tu consulta en este momento. 😔")
                
                # Extraer nombre del mensaje (si se indica)
                data_from_msg = extract_user_data(plain_body)
                if partner:
                    # Si se recibe un nombre en el mensaje y éste es distinto al que ya está, lo actualizamos
                    if data_from_msg.get("name") and (not partner.name or data_from_msg.get("name").lower() != partner.name.lower()):
                        _logger.info("Actualizando nombre del partner (ID %s) de '%s' a '%s'", partner.id, partner.name, data_from_msg.get("name"))
                        partner.sudo().write({"name": data_from_msg.get("name")})
                    # Si ya existe un nombre, NO se agrega la solicitud de nombre
                else:
                    partner = self.env['res.partner'].sudo().create({
                        'phone': normalized_phone,
                        'name': data_from_msg.get("name") or "",
                    })
                    if not data_from_msg.get("name"):
                        response_text += " Por cierto, ¿cómo te llamás? 😊"
                
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
                    outgoing_msg.sudo().write({'body': response_text})
                    _logger.info("Mensaje saliente creado: ID %s, body: %s", outgoing_msg.id, outgoing_msg.body)
                    if hasattr(outgoing_msg, '_send_message'):
                        outgoing_msg._send_message()
                    else:
                        _logger.info("Método _send_message no disponible; el mensaje quedará en cola.")
                except Exception as e:
                    _logger.error("Error al crear/enviar mensaje saliente para mensaje %s: %s", message.id, e)

                # Actualizar datos del partner (correo y nombre) si aparecen en el mensaje
                if partner:
                    data = extract_user_data(plain_body)
                    updates = {}
                    if data.get("name") and (not partner.name or data.get("name").lower() != partner.name.lower()):
                        updates["name"] = data["name"]
                    if data.get("email") and (not partner.email or data.get("email").lower() != partner.email.lower()):
                        updates["email"] = data["email"]
                    if updates:
                        _logger.info("Actualizando partner %s: %s", partner.id, updates)
                        partner.sudo().write(updates)
        return records

    def _handle_product_query(self, user_text):
        """
        Responde de forma persuasiva para consultas de productos, redirigiendo al usuario a la web.
        """
        return ("¡Hola! Para encontrar el producto o alternativa que buscas, "
                "te invito a visitar nuestra tienda en línea en www.quimicacristal.com. "
                "Ahí encontrarás justo lo que necesitas. ¡No lo dejes pasar, compra ahora! 😊🛒")

    def _generate_chatbot_reply(self, user_text):
        """
        Genera una respuesta conversacional utilizando OpenAI con un tono muy casual, cercano y persuasivo.
        Se apoya en el contexto de los últimos 5 mensajes e inyecta el nombre del cliente (si se conoce)
        en el prompt para tratarlo de forma personalizada.
        """
        mobile_to_use = self.mobile_number if isinstance(self.mobile_number, str) else ""
        normalized_mobile = normalize_phone(mobile_to_use)
        partner = self.env['res.partner'].sudo().search([
            '|',
            ('phone', 'ilike', normalized_mobile),
            ('mobile', 'ilike', normalized_mobile)
        ], limit=1)
        extra_prompt = ""
        if partner and partner.name:
            extra_prompt = f" Recuerda que el cliente se llama {partner.name}."
            
        api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key') or environ.get('OPENAI_API_KEY')
        if not api_key:
            _logger.error("La API key de OpenAI no está configurada.")
            return _("Lo siento, no pude procesar tu mensaje. 😔")
        openai.api_key = api_key

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

        already_greeted = False
        recent_outgoing = self.env['whatsapp.message'].sudo().search([
            ('mobile_number', '=', self.mobile_number),
            ('state', '=', 'outgoing')
        ], order='id desc', limit=1)
        if recent_outgoing and has_greeting(clean_html(recent_outgoing.body)):
            already_greeted = True

        system_prompt = (
            "Eres el asistente virtual de atención al cliente de Química Cristal Minorista, especializada en la venta de insumos de limpieza para el hogar. "
            "Habla de forma muy casual, cercana y amigable, usando un tono personal y persuasivo, e incorpora emojis en tus respuestas. "
            "Cuando un usuario pregunte por un producto, redirígalo a nuestra web (www.quimicacristal.com) con un claro llamado a la acción, "
            "por ejemplo, '¡Compra ahora!' o 'Visita nuestra web'. Si el usuario pregunta por la ubicación o los horarios, incluye ambos datos. "
            "Sé conciso y no repitas saludos innecesarios. " + extra_prompt
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
            if has_greeting(reply_text) and already_greeted:
                lines = reply_text.splitlines()
                if len(lines) > 1:
                    reply_text = "\n".join(lines[1:]).strip()
            return reply_text
        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e, exc_info=True)
            return _("Lo siento, hubo un problema técnico al generar la respuesta. 😔")
