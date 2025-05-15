# -*- coding: utf-8 -*-
from odoo import models, api, _
import openai
import logging
import re
from os import environ

_logger = logging.getLogger(__name__)

HTML_TAGS = re.compile(r"<[^>]+>")
def clean_html(text): return re.sub(HTML_TAGS, "", text or "").strip()

def normalize_phone(phone):
    phone_norm = phone.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if phone_norm.startswith('549'): phone_norm = phone_norm[3:]
    elif phone_norm.startswith('54'): phone_norm = phone_norm[2:]
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

REGALO_KEYWORDS = ['quiero mi regalo', 'regalo', '🎁']
WEB_KEYWORDS = ['web', 'tienda', 'online', 'comprar']
LOCAL_KEYWORDS = ['local', 'negocio', 'físico', 'fisico']

RESPUESTA_INICIAL = (
    "🎉 ¡Felicitaciones! Ganaste hasta $10.000 en productos de limpieza.\n"
    "¿Querés usar tu regalo en la Tienda Web 🛒 o en el Local Físico 🏪?\n"
    "Respondé con 'Web', 'Tienda', 'Online' o 'Local', 'Negocio', etc."
)
RESPUESTA_CUPON = "Tenés 3 días para usarlo. Si se te complica, avisanos 😉"

def contiene_palabra_clave(texto, palabras_clave):
    return any(palabra.lower() in texto.lower() for palabra in palabras_clave)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super(WhatsAppMessage, self).create(vals_list)
        for message in records:
            plain_body = clean_html(message.body)
            if message.state != 'received' or not message.mobile_number or not plain_body:
                continue

            texto = plain_body.lower()
            normalized_phone = normalize_phone(message.mobile_number)

            partner = self.env['res.partner'].sudo().search([
                '|',
                ('phone', 'ilike', normalized_phone),
                ('mobile', 'ilike', normalized_phone)
            ], limit=1)

            # Crear partner si no existe
            if not partner:
                partner = self.env['res.partner'].sudo().create({'phone': normalized_phone})

            # Solo responder si hay palabra clave
            if contiene_palabra_clave(texto, REGALO_KEYWORDS):
                self._crear_mensaje_salida(message, RESPUESTA_INICIAL)
            elif contiene_palabra_clave(texto, WEB_KEYWORDS) or contiene_palabra_clave(texto, LOCAL_KEYWORDS):
                self._enviar_cupon(message)
            else:
                continue  # No responder a ningún otro mensaje

        return records

    def _crear_mensaje_salida(self, mensaje_entrada, texto):
        vals = {
            'mobile_number': mensaje_entrada.mobile_number,
            'body': texto,
            'state': 'outgoing',
            'create_uid': self.env.ref('base.user_admin').id,
            'wa_account_id': mensaje_entrada.wa_account_id.id if mensaje_entrada.wa_account_id else False,
        }
        mensaje_saliente = self.env['whatsapp.message'].sudo().create(vals)
        if hasattr(mensaje_saliente, '_send_message'):
            mensaje_saliente._send_message()
        else:
            _logger.warning("No se pudo enviar el mensaje saliente (sin método _send_message).")

    def _enviar_cupon(self, mensaje_entrada):
        adjunto = self.env['ir.attachment'].sudo().search([('name', '=', 'cupon_web')], limit=1)
        if not adjunto:
            _logger.warning("Imagen de cupón 'cupon_web' no encontrada.")
            return

        vals = {
            'mobile_number': mensaje_entrada.mobile_number,
            'body': RESPUESTA_CUPON,
            'attachment_ids': [(6, 0, [adjunto.id])],
            'state': 'outgoing',
            'create_uid': self.env.ref('base.user_admin').id,
            'wa_account_id': mensaje_entrada.wa_account_id.id if mensaje_entrada.wa_account_id else False,
        }
        mensaje = self.env['whatsapp.message'].sudo().create(vals)
        if hasattr(mensaje, '_send_message'):
            mensaje._send_message()
        else:
            _logger.warning("No se pudo enviar el cupón (sin método _send_message).")
