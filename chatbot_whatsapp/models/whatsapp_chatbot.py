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
    eliminando prefijos internacionales.
    """
    phone_norm = phone.replace('+', '').replace(' ', '')\
                      .replace('-', '').replace('(', '')\
                      .replace(')', '')
    if phone_norm.startswith('549'):
        phone_norm = phone_norm[3:]
    elif phone_norm.startswith('54'):
        phone_norm = phone_norm[2:]
    return phone_norm

def extract_user_data(text):
    """
    Extrae nombre y correo a partir de frases tipo "me llamo", "soy",
    o "mi nombre es", y busca emails de dominios comunes.
    """
    name_pat  = r"(?:me llamo|soy|mi nombre es)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+)*)"
    email_pat = r"[\w\.\-]+@(?:gmail|hotmail|yahoo|outlook|icloud)\.(?:com|ar)"
    name_m = re.search(name_pat, text, re.IGNORECASE)
    email_m = re.search(email_pat, text)
    return {
        "name":  name_m.group(1).strip() if name_m else None,
        "email": email_m.group(0)          if email_m else None,
    }

def has_greeting(text):
    greetings = ("hola", "buenos días", "buenas tardes", "buenas noches", "qué tal")
    return any(g in text.lower() for g in greetings)

def has_product_keywords(text):
    kws = ("comprar", "producto", "oferta", "catálogo", "precio",
           "jabón", "cera", "detergente", "pisos")
    return any(kw in text.lower() for kw in kws)

def is_valid_product_query(user_text):
    allowed = [
        "combos", "ofertas", "líquidos de limpieza", "lavandinas",
        "detergentes", "limpiadores desodorantes", "desengrasantes",
        "desinfectantes", "insecticida", "mantenimiento de pisos",
        "químicos para piletas", "higiene personal", "lampazos",
        # … sigue toda la lista original …
    ]
    txt = user_text.lower()
    return any(kw in txt for kw in allowed)

def is_obscene_query(user_text):
    obscene = ["dildo", "dildos", "pene de goma", "penes de goma"]
    txt = user_text.lower()
    return any(term in txt for term in obscene)

# -----------------------------------------------------------
# RESPUESTAS DE “REGALO”
# -----------------------------------------------------------
REGALO_KEYWORDS = ['quiero mi regalo', 'regalo', '🎁']
RESPUESTA_INICIAL = (
    "🎉 ¡Felicitaciones! Ganaste hasta $10.000 en productos de limpieza.\n"
    "¿Querés usar tu regalo en la Tienda Web 🛒 o en el Local Físico 🏪?\n"
    "Respondé con 'Web', 'Tienda', 'Online' o 'Local', 'Negocio', etc."
)

def contains_any(text, lst):
    txt = text or ""
    return any(w.lower() in txt.lower() for w in lst)

# -----------------------------------------------------------
# RESPUESTAS FAQ (BASADAS EN REGLAS)
# -----------------------------------------------------------
FAQ_RESPONSES = {
    "horario": ("Nuestros horarios de atención son: lunes a viernes de 8:30 a 12:30 "
                "y de 16:00 a 20:00, sábados de 9:00 a 13:00. "
                "Estamos en San Martin 2350, Río Cuarto, Córdoba. 😊"),
    # … mantiene todas las entradas originales …
}

def check_faq(user_text):
    lower = user_text.lower()
    for key, ans in FAQ_RESPONSES.items():
        if key in lower:
            return ans
    return None

# -----------------------------------------------------------
# MODELO EXTENDIDO: WhatsAppMessage
# -----------------------------------------------------------
class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for message in records:
            plain = clean_html(message.body)
            # Sólo recibidos válidos
            if message.state != 'received' or not message.mobile_number or not plain:
                continue

            # —————————————
            # 1) LÓGICA “REGALO”
            # —————————————
            if contains_any(plain, REGALO_KEYWORDS):
                # envía el primer mensaje de “Felicitaciones…”
                self._crear_mensaje_salida(
                    message,
                    RESPUESTA_INICIAL
                )
                # y ya no sigue con IA/FAQ/etc para este mensaje
                continue

            # —————————————
            # 2) LÓGICA EXISTENTE DE “LEON” (IA, FAQ, productos…)
            # —————————————
            _logger.info("Mensaje recibido (ID %s): %s", message.id, plain)
            normalized = normalize_phone(message.mobile_number)
            partner = self.env['res.partner'].sudo().search([
                '|', ('phone', 'ilike', normalized),
                     ('mobile','ilike', normalized)
            ], limit=1)

            # obsceno?
            if is_obscene_query(plain):
                response = (
                    "Lo siento, en Química Cristal Minorista nos especializamos "
                    "en insumos de limpieza. Visita nuestro catálogo en "
                    "www.quimicacristal.com 😊"
                )
            else:
                faq = check_faq(plain)
                if faq:
                    response = faq
                elif has_product_keywords(plain):
                    if is_valid_product_query(plain):
                        response = self._handle_product_query(plain)
                    else:
                        response = (
                            "Lo siento, en Química Cristal Minorista nos especializamos "
                            "en insumos de limpieza para el hogar. 😉"
                        )
                else:
                    response = self._generate_chatbot_reply(plain)

            # … aquí sigue exactamente el cuerpo original:
            response_text = str(response).strip() or _(
                "Lo siento, no pude procesar tu consulta en este momento. 😔"
            )
            data = extract_user_data(plain)
            # … lógica de update/create partner …
            # … envío del mensaje saliente idéntico …
            try:
                outgoing_vals = {
                    'mobile_number': message.mobile_number,
                    'body': response_text,
                    'state': 'outgoing',
                    'create_uid': self.env.ref('base.user_admin').id,
                    'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
                }
                out = self.env['whatsapp.message'].sudo().create(outgoing_vals)
                out.sudo().write({'body': response_text})
                if hasattr(out, '_send_message'):
                    out._send_message()
            except Exception as e:
                _logger.error(
                    "Error al crear/enviar mensaje saliente para %s: %s",
                    message.id, e
                )
            # … y actualización final de datos en partner …

        return records

    # Métodos auxiliares originales de “Leon”:
    def _handle_product_query(self, user_text):
        return (
            "¡Hola! Para encontrar el producto o alternativa que buscas, "
            "visita nuestra tienda en línea en www.quimicacristal.com. 🛒"
        )

    def _generate_chatbot_reply(self, user_text):
        # … todo idéntico al original …
        # construye prompt, llama a OpenAI, retorna reply_text
        pass
