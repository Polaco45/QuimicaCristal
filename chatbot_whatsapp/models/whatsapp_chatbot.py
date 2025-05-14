# -*- coding: utf-8 -*-
from odoo import models, api, _
import openai
import logging
import re
from os import environ

_logger = logging.getLogger(__name__)

HTML_TAGS = re.compile(r"<[^>]+>")

def clean_html(text):
    return re.sub(HTML_TAGS, "", text or "").strip()

def normalize_phone(phone):
    phone_norm = phone.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if phone_norm.startswith('549'):
        phone_norm = phone_norm[3:]
    elif phone_norm.startswith('54'):
        phone_norm = phone_norm[2:]
    return phone_norm

def extract_user_data(text):
    name_pat = r"(?:me llamo|soy|mi nombre es)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+)*)"
    email_pat = r"[\w\.\-]+@(?:gmail|hotmail|yahoo|outlook|icloud)\.(?:com|ar)"
    name_match = re.search(name_pat, text, re.IGNORECASE)
    email_match = re.search(email_pat, text)
    return {
        "name": name_match.group(1).strip() if name_match else None,
        "email": email_match.group(0) if email_match else None,
    }

def has_greeting(text):
    greetings = ("hola", "buenos días", "buenas tardes", "buenas noches", "qué tal")
    return any(g in text.lower() for g in greetings)

def has_product_keywords(text):
    keywords = ("comprar", "producto", "oferta", "catálogo", "precio", "jabón", "cera", "detergente", "pisos")
    return any(kw in text.lower() for kw in keywords)

def is_valid_product_query(user_text):
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
    obscene_terms = ["dildo", "dildos", "pene de goma", "penes de goma"]
    text_lower = user_text.lower()
    for term in obscene_terms:
        if term in text_lower:
            return True
    return False

FAQ_RESPONSES = {
    "horario": "Nuestros horarios de atención son: lunes a viernes de 8:30 a 12:30 y de 16:00 a 20:00, y sábados de 9:00 a 13:00. Además, nos encontrás en San Martin 2350, Río Cuarto, Córdoba. Visita www.quimicacristal.com 😊",
    "horarios": "Nuestros horarios de atención son: lunes a viernes de 8:30 a 12:30 y de 16:00 a 20:00, y sábados de 9:00 a 13:00. Estamos en San Martin 2350, Río Cuarto. Más info en www.quimicacristal.com 😊",
    "estado de cuenta": "Para ver tu estado de cuenta, ingresá a www.quimicacristal.com 💻",
    "que haces": "Soy tu asistente de Química Cristal y estoy acá para ayudarte con productos, horarios o tu cuenta. 🤖",
    "local": "Nuestro local está en San Martin 2350, Río Cuarto. Horarios: lun a vie de 8:30 a 12:30 y 16:00 a 20:00, sábados de 9:00 a 13:00. 📍",
    "dirección": "Estamos en San Martin 2350, Río Cuarto. Más info en www.quimicacristal.com 📍",
    "ubicación": "San Martin 2350, Río Cuarto, Córdoba. Horarios: lun a vie 8:30–12:30 / 16:00–20:00, sáb 9:00–13:00. Más info en la web 📍",
}

def check_faq(user_text):
    lower_text = user_text.lower()
    for key, answer in FAQ_RESPONSES.items():
        if key in lower_text:
            return answer
    return None

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for message in records:
            plain_body = clean_html(message.body)
            if message.state == 'received' and message.mobile_number and plain_body:
                _logger.info("Mensaje recibido (ID %s): %s", message.id, plain_body)
                normalized_phone = normalize_phone(message.mobile_number)

                partner = self.env['res.partner'].sudo().search([
                    '|',
                    ('phone', 'ilike', normalized_phone),
                    ('mobile', 'ilike', normalized_phone)
                ], limit=1)

                if is_obscene_query(plain_body):
                    response = ("Lo siento, nos especializamos en productos de limpieza. Mirá el catálogo en www.quimicacristal.com")
                else:
                    faq_answer = check_faq(plain_body)
                    if faq_answer:
                        response = faq_answer
                    elif has_product_keywords(plain_body):
                        if is_valid_product_query(plain_body):
                            response = self._handle_product_query(plain_body)
                        else:
                            response = ("En Química Cristal nos enfocamos en productos de limpieza y hogar. Mirá todo en www.quimicacristal.com 😉")
                    else:
                        response = self._generate_chatbot_reply(plain_body)

                response_text = response.strip() if response else _("Lo siento, no pude procesar tu consulta. 😔")

                if not partner:
                    partner = self.env['res.partner'].sudo().create({
                        'phone': normalized_phone,
                        'name': "",
                    })
                    response_text += " Por cierto, ¿cómo te llamás? 😊"

                try:
                    outgoing_vals = {
                        'mobile_number': message.mobile_number,
                        'body': response_text,
                        'state': 'outgoing',
                        'create_uid': self.env.ref('base.user_admin').id,
                        'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
                    }
                    outgoing_msg = self.env['whatsapp.message'].sudo().create(outgoing_vals)
                    if hasattr(outgoing_msg, '_send_message'):
                        outgoing_msg._send_message()
                except Exception as e:
                    _logger.error("Error al enviar mensaje saliente: %s", e)

        return records

    def _handle_product_query(self, user_text):
        return ("¡Hola! Para ver nuestros productos y comprar online, ingresá a www.quimicacristal.com. ¡Hay ofertas esperándote! 🛒😊")

    def _generate_chatbot_reply(self, user_text):
        mobile_to_use = self.mobile_number if isinstance(self.mobile_number, str) else ""
        normalized_mobile = normalize_phone(mobile_to_use)

        extra_prompt = ""  # ← CORRECTAMENTE INDENTADO

        api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key') or environ.get('OPENAI_API_KEY')
        if not api_key:
            _logger.error("Falta la API KEY de OpenAI.")
            return _("Lo siento, no pude procesar tu mensaje. 😔")

        openai.api_key = api_key

        recent_msgs = self.env['whatsapp.message'].sudo().search([
            ('mobile_number', '=', self.mobile_number),
            ('id', '<', self.id),
            ('body', '!=', False)
        ], order='id desc', limit=5)

        context = [{"role": 'user' if m.state == 'received' else 'assistant', "content": clean_html(m.body)} for m in reversed(recent_msgs)]
        context.append({"role": "user", "content": user_text})

        messages = [{
            "role": "system",
            "content": (
                "Sos el asistente virtual de Química Cristal Minorista. "
                "Respondé con un tono casual, persuasivo y con emojis. "
                "Si te preguntan por productos, redirigí a www.quimicacristal.com con un llamado a la acción. "
                "No repitas saludos si ya se saludó antes. " + extra_prompt
            )
        }] + context

        try:
            reply_result = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.45,
                max_tokens=200,
            )
            reply_text = reply_result.choices[0].message.content.strip()
            return reply_text
        except Exception as e:
            _logger.error("Error OpenAI: %s", e, exc_info=True)
            return _("Lo siento, hubo un problema al generar la respuesta. 😔")

