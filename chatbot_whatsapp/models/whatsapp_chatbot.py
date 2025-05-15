# -*- coding: utf-8 -*-
from odoo import models, api, _, exceptions
import logging
import re

_logger = logging.getLogger(__name__)

# -----------------------------------------------------------
# UTILIDADES
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

# -----------------------------------------------------------
# PALABRAS CLAVE Y RESPUESTAS
# -----------------------------------------------------------
REGALO_KEYWORDS = ['quiero mi regalo', 'regalo', '🎁']
WEB_KEYWORDS    = ['web', 'tienda', 'online', 'comprar']
LOCAL_KEYWORDS  = ['local', 'negocio', 'físico', 'fisico']

RESPUESTA_INICIAL = (
    "🎉 ¡Felicitaciones! Ganaste hasta $10.000 en productos de limpieza.\n"
    "¿Querés usar tu regalo en la Tienda Web 🛒 o en el Local Físico 🏪?\n"
    "Respondé con 'Web', 'Tienda', 'Online' o 'Local', 'Negocio', etc."
)
RESPUESTA_CUPON = "Tenés 3 días para usarlo. Si se te complica, avisanos 😉"

def contiene_palabra_clave(texto, palabras_clave):
    return any(palabra.lower() in texto.lower() for palabra in palabras_clave)

# -----------------------------------------------------------
# MODELO EXTENDIDO: WhatsAppMessage
# -----------------------------------------------------------
class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        # ─── 1) Inyectar credenciales de la cuenta de WhatsApp ─────────────────
        for vals in vals_list:
            acct_id = vals.get('wa_account_id')
            acct = self.env['whatsapp.account'].browse(acct_id)
            if not acct:
                raise exceptions.UserError(_("No hay ninguna cuenta de WhatsApp configurada."))
            if not acct.access_token or not acct.phone_number_id:
                raise exceptions.UserError(_("Credenciales de WhatsApp no configuradas en la cuenta."))
            # Inyectamos:
            vals['access_token']    = acct.access_token
            vals['phone_number_id'] = acct.phone_number_id

        # ─── 2) Creamos los registros (entrantes y salientes) ─────────────────
        records = super(WhatsAppMessage, self).create(vals_list)

        # ─── 3) Procesamos SOLO los entrantes y disparamos las respuestas ─────────────────
        for message in records:
            if message.state != 'received' or not message.mobile_number or not message.body:
                continue

            plain = clean_html(message.body)
            texto = plain.lower()

            #  Normalizamos y buscamos partner
            phone_norm = normalize_phone(message.mobile_number)
            partner = self.env['res.partner'].sudo().search([
                '|', ('phone', 'ilike', phone_norm),
                     ('mobile','ilike', phone_norm)
            ], limit=1)
            if not partner:
                partner = self.env['res.partner'].sudo().create({'phone': phone_norm})

            # ─── 4) Lógica de respuesta según palabra clave ─────────────────
            if contiene_palabra_clave(texto, REGALO_KEYWORDS):
                # primer mensaje de felicitación
                self._crear_mensaje_salida(message, RESPUESTA_INICIAL)
            elif contiene_palabra_clave(texto, WEB_KEYWORDS) or \
                 contiene_palabra_clave(texto, LOCAL_KEYWORDS):
                # segundo paso, envío de cupón con imagen
                self._enviar_cupon(message)
            else:
                # ignoramos cualquier otro texto
                continue

        return records

    def _crear_mensaje_salida(self, mensaje_entrada, texto):
        vals = {
            'mobile_number': mensaje_entrada.mobile_number,
            'body': texto,
            'state': 'outgoing',
            'create_uid': self.env.ref('base.user_admin').id,
            'wa_account_id': mensaje_entrada.wa_account_id.id,
            # Ya inyectamos access_token y phone_number_id en el create()
        }
        msg = self.env['whatsapp.message'].sudo().create(vals)
        if hasattr(msg, '_send_message'):
            msg._send_message()
        else:
            _logger.warning("No se pudo enviar el mensaje saliente (falta método _send_message).")

    def _enviar_cupon(self, mensaje_entrada):
        adj = self.env['ir.attachment'].sudo().search([('name','=','cupon_web')], limit=1)
        if not adj:
            _logger.warning("Imagen de cupón 'cupon_web' no encontrada.")
            return
        vals = {
            'mobile_number': mensaje_entrada.mobile_number,
            'body': RESPUESTA_CUPON,
            'attachment_ids': [(6,0,[adj.id])],
            'state': 'outgoing',
            'create_uid': self.env.ref('base.user_admin').id,
            'wa_account_id': mensaje_entrada.wa_account_id.id,
            # También heredamos access_token y phone_number_id
        }
        msg = self.env['whatsapp.message'].sudo().create(vals)
        if hasattr(msg, '_send_message'):
            msg._send_message()
        else:
            _logger.warning("No se pudo enviar el cupón (falta método _send_message).")
