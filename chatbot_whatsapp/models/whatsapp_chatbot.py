# -*- coding: utf-8 -*-
import re
import logging
import requests
import openai

from odoo import models, api, _
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

def is_obscene_query(text):
    for term in ("dildo", "dildos", "pene de goma", "penes de goma"):
        if term in text.lower():
            return True
    return False

FAQ_RESPONSES = {
    "horario": "Nuestros horarios son lun-vie 8:30-12:30 y 16:00-20:00, sáb 9:00-13:00. San Martin 2350, Río Cuarto. 😊",
    "dirección": "Estamos en San Martin 2350, Río Cuarto. Horarios lun-vie 8:30-12:30/16:00-20:00, sáb 9:00-13:00.",
    "ubicación": "San Martin 2350, Río Cuarto, Córdoba. 📍",
    "que haces": "Soy tu asistente de Química Cristal, listo para ayudarte con productos, horarios o tu cuenta. 🤖",
}

def check_faq(text):
    tl = text.lower()
    for k, a in FAQ_RESPONSES.items():
        if k in tl:
            return a
    return None

def has_product_keywords(text):
    for kw in ("comprar","producto","oferta","catálogo","precio","jabón","cera","detergente","pisos"):
        if kw in text.lower():
            return True
    return False

def is_valid_product_query(text):
    allowed = ["combos","ofertas","lavandinas","detergentes","desinfectantes","insecticida",
               "limpiavidrios","químicos para piletas","higiene personal","mopas","baldes",
               "guantes","sopapas","bolsas","trapos","cestos","escobillones","cepillos"]
    tl = text.lower()
    return any(kw in tl for kw in allowed)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for msg in records:
            plain = clean_html(msg.body)
            if msg.state == 'received' and msg.mobile_number and plain:
                _logger.info("📩 Mensaje recibido ID %s: %s", msg.id, plain)
                phone = normalize_phone(msg.mobile_number)

                partner = self.env['res.partner'].sudo().search([
                    '|', ('phone','ilike',phone), ('mobile','ilike',phone)
                ], limit=1)

                # Determinar la respuesta
                if is_obscene_query(plain):
                    resp = "Lo siento, en Química Cristal solo vendemos insumos de limpieza. Mirá nuestro catálogo online."
                else:
                    faq = check_faq(plain)
                    if faq:
                        resp = faq
                    elif has_product_keywords(plain):
                        if is_valid_product_query(plain):
                            resp = "¡Visita ya nuestra tienda online en www.quimicacristal.com y aprovechá las ofertas! 🛒😊"
                        else:
                            resp = "En Química Cristal nos enfocamos en limpieza y hogar. Todos los productos en www.quimicacristal.com 😉"
                    else:
                        resp = self._generate_chatbot_reply(plain)

                if not partner:
                    partner = self.env['res.partner'].sudo().create({
                        'phone': phone, 'name': '',
                    })
                    resp += " Por cierto, ¿cómo te llamás? 😊"

                # ——— Envío vía Facebook Graph API ———
                # Ahora obtenemos siempre de ir.config_parameter (o variable de entorno)
                token = (
                    self.env['ir.config_parameter'].sudo()
                        .get_param('whatsapp.access_token')
                    or environ.get('WHATSAPP_ACCESS_TOKEN')
                )
                phone_id = (
                    self.env['ir.config_parameter'].sudo()
                        .get_param('whatsapp.phone_number_id')
                )
                if not token or not phone_id:
                    _logger.error("❌ Credenciales de WhatsApp no configuradas en ir.config_parameter.")
                    continue

                url = f"https://graph.facebook.com/v14.0/{phone_id}/messages"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "messaging_product": "whatsapp",
                    "to": phone,
                    "text": {"body": resp},
                }

                try:
                    r = requests.post(url, headers=headers, json=payload, timeout=5)
                    r.raise_for_status()
                    _logger.info("✅ Enviado a %s -> %s", phone, r.json())
                except Exception as e:
                    _logger.error("❌ Error GraphAPI: %s", e)

        return records

    def _generate_chatbot_reply(self, user_text):
        api_key = (
            self.env['ir.config_parameter'].sudo()
                .get_param('openai.api_key')
            or environ.get('OPENAI_API_KEY')
        )
        if not api_key:
            _logger.error("❌ Falta openai.api_key.")
            return _("Lo siento, no pude procesar tu mensaje. 😔")
        openai.api_key = api_key

        prev = self.env['whatsapp.message'].sudo().search([
            ('mobile_number','=', self.mobile_number),
            ('id','<', self.id),
            ('body','!=', False),
        ], order='id desc', limit=5)
        msgs = [{"role": ('user' if m.state=='received' else 'assistant'),
                 "content": clean_html(m.body)} for m in reversed(prev)]
        msgs.append({"role": "user", "content": user_text})

        sys = {
            "role": "system",
            "content": (
                "Sos el asistente virtual de Química Cristal Minorista. "
                "Respondé con tono casual, cercano y persuasivo, usando emojis. "
                "Si preguntan por productos, referilos siempre a www.quimicacristal.com con un claro llamado a la acción."
            ),
        }

        try:
            reply = openai.ChatCompletion.create(
                model="gpt-3.5-turbo", messages=[sys] + msgs,
                temperature=0.5, max_tokens=200,
            )
            return reply.choices[0].message.content.strip()
        except Exception as e:
            _logger.error("❌ Error OpenAI: %s", e, exc_info=True)
            return _("Lo siento, hubo un problema técnico. 😔")
