# -*- coding: utf-8 -*-  
from odoo import models, api, _
import openai
import logging
import re
from os import environ

_logger = logging.getLogger(__name__)

# -----------------------------------------------------------
# UTILIDADES GENERALES (igual que antes)
# -----------------------------------------------------------
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
    allowed = [ ... ]  # idéntico a Leon, lista de categorías
    text_lower = user_text.lower()
    return any(kw in text_lower for kw in allowed)

def is_obscene_query(user_text):
    obscene = ["dildo", "dildos", "pene de goma", "penes de goma"]
    tl = user_text.lower()
    return any(o in tl for o in obscene)

FAQ_RESPONSES = { ... }  # idéntico a Leon
def check_faq(user_text):
    lt = user_text.lower()
    for k,a in FAQ_RESPONSES.items():
        if k in lt:
            return a
    return None

# -----------------------------------------------------------
# NUEVA LÓGICA “REGALO 10K” (añadida sobre Leon)
# -----------------------------------------------------------
REGALO_KEYWORDS = ['quiero mi regalo', 'regalo', '🎁']
ELEC_WEB      = ['web', 'tienda', 'online', 'comprar']
ELEC_LOCAL    = ['local', 'negocio', 'físico', 'fisico']
RESPUESTA_INICIAL = (
    "🎉 ¡Felicitaciones! Ganaste hasta $10.000 en productos de limpieza.\n"
    "¿Querés usar tu regalo en la Tienda Web 🛒 o en el Local Físico 🏪?\n"
    "Respondé con 'Web', 'Tienda', 'Online' o 'Local', 'Negocio', etc."
)
RESPUESTA_CUPON = "Tenés 3 días para usarlo. Si se te complica, ¡avisanos! 😉"

def contains_any(text, lst):
    tl = text.lower()
    return any(w in tl for w in lst)

# -----------------------------------------------------------
# MODELO EXTENDIDO: WhatsAppMessage
# -----------------------------------------------------------
class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for msg in records:
            if msg.state!='received' or not msg.mobile_number or not msg.body:
                continue

            plain = clean_html(msg.body)
            low = plain.lower()

            # --- 1) Inicio regalo
            if contains_any(low, REGALO_KEYWORDS):
                self._crear_mensaje_salida(msg, RESPUESTA_INICIAL)
                continue

            # --- 2) Elección Web / Local
            if contains_any(low, ELEC_WEB) or contains_any(low, ELEC_LOCAL):
                self._enviar_cupon(msg)
                continue

            # --- 3) Resto de Leon intacto
            _logger.info("Mensaje recibido (ID %s): %s", msg.id, plain)
            normalized = normalize_phone(msg.mobile_number)
            partner = self.env['res.partner'].sudo().search([
                '|',('phone','ilike',normalized),('mobile','ilike',normalized)
            ], limit=1)

            if is_obscene_query(plain):
                response = _("Lo siento, en Química Cristal Minorista sólo vendemos insumos de limpieza.")
            else:
                faq = check_faq(plain)
                if faq:
                    response = faq
                elif has_product_keywords(plain):
                    if is_valid_product_query(plain):
                        response = self._handle_product_query(plain)
                    else:
                        response = _("Lo siento, especializ. en insumos de limpieza. Visita nuestro catálogo.")
                else:
                    response = self._generate_chatbot_reply(plain)

            resp_txt = response.strip() or _("Lo siento, no pude procesar tu consulta. 😔")
            # guardamos partner, extraemos datos, etc. (idéntico a Leon)
            # ...
            # enviamos la respuesta
            self._crear_mensaje_salida(msg, resp_txt)
        return records

    def _crear_mensaje_salida(self, entrada, texto):
        vals = {
            'mobile_number': entrada.mobile_number,
            'body': texto,
            'state': 'outgoing',
            'create_uid': self.env.ref('base.user_admin').id,
            'wa_account_id': entrada.wa_account_id.id if entrada.wa_account_id else False,
        }
        out = self.env['whatsapp.message'].sudo().create(vals)
        if hasattr(out,'_send_message'):
            out._send_message()

    def _enviar_cupon(self, entrada):
        att = self.env['ir.attachment'].sudo().search([('name','=','cupon_web')], limit=1)
        if not att:
            _logger.warning("Cupón no encontrado")
            return
        vals = {
            'mobile_number': entrada.mobile_number,
            'body': RESPUESTA_CUPON,
            'attachment_ids': [(6,0,[att.id])],
            'state': 'outgoing',
            'create_uid': self.env.ref('base.user_admin').id,
            'wa_account_id': entrada.wa_account_id.id if entrada.wa_account_id else False,
        }
        out = self.env['whatsapp.message'].sudo().create(vals)
        if hasattr(out,'_send_message'):
            out._send_message()

    # _handle_product_query, _generate_chatbot_reply, etc. → idénticos a Leon
