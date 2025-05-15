# -*- coding: utf-8 -*-
from odoo import models, api, _
import logging
import re

_logger = logging.getLogger(__name__)

TRIGGER_WORDS = [
    "quiero mi regalo", "quiero mi Regalo", "regalo", "Regalo", "🎁",
    "mi regalo", "el regalo", "promo", "promoción", "cupon", "cupón"
]

WEB_KEYWORDS = ["web", "tienda", "online", "sitio", "página"]
LOCAL_KEYWORDS = ["local", "físico", "negocio", "sucursal", "ir personalmente"]

class WhatsappMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for msg in records:
            if msg.state != 'received' or not msg.body:
                continue

            texto = msg.body.strip().lower()

            # Verificamos si el mensaje es uno de los disparadores
            if any(palabra in texto for palabra in TRIGGER_WORDS):
                respuesta = "🎉 ¡Felicitaciones! Ganaste hasta $10.000 en productos.\n¿Querés usarlo en la web 🛒 o en el local 🏪?"
                self._responder(msg, respuesta)

            elif any(palabra in texto for palabra in WEB_KEYWORDS + LOCAL_KEYWORDS):
                imagen = self.env['ir.attachment'].search([('name', '=', 'cupon_web')], limit=1)
                if imagen:
                    msg.env['whatsapp.message'].sudo().create({
                        'mobile_number': msg.mobile_number,
                        'state': 'outgoing',
                        'attachment_id': imagen.id,
                        'wa_account_id': msg.wa_account_id.id,
                    })
                texto = "Tenés 3 días para usarlo. Si se te complica, escribinos 😉"
                self._responder(msg, texto)

        return records

    def _responder(self, mensaje_obj, texto):
        """Crea y envía una respuesta simple por WhatsApp"""
        try:
            outgoing_msg = self.env['whatsapp.message'].sudo().create({
                'mobile_number': mensaje_obj.mobile_number,
                'body': texto,
                'state': 'outgoing',
                'create_uid': self.env.ref('base.user_admin').id,
                'wa_account_id': mensaje_obj.wa_account_id.id,
            })
            if hasattr(outgoing_msg, '_send_message'):
                outgoing_msg._send_message()
        except Exception as e:
            _logger.error("❌ Error al enviar respuesta automática: %s", e)
