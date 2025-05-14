# -*- coding: utf-8 -*-
from odoo import models, api, _
import logging
import re

_logger = logging.getLogger(__name__)

def clean_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()

def normalize_phone(phone):
    phone_norm = phone.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if phone_norm.startswith('549'):
        phone_norm = phone_norm[3:]
    elif phone_norm.startswith('54'):
        phone_norm = phone_norm[2:]
    return phone_norm

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for message in records:
            plain_body = clean_html(message.body or "")
            if message.state != 'received' or not message.mobile_number:
                continue

            lower_body = plain_body.lower()

            # Activación: si escriben "quiero mi regalo"
            if "quiero mi regalo" in lower_body:
                self._responder_bienvenida(message)
            elif lower_body in ["tienda web", "web"]:
                self._enviar_cupon(message, destino='web')
            elif lower_body in ["local físico", "local", "físico"]:
                self._enviar_cupon(message, destino='local')
            else:
                _logger.info("Mensaje ignorado por no ser parte del flujo del regalo.")
        return records

    def _responder_bienvenida(self, message):
        texto = (
            "🎁 ¡Genial! Estás participando de la promo de Química Cristal. "
            "Tenés un regalo de $10.000 para usar en tu primera compra. "
            "¿Dónde preferís usarlo?\n\n"
            "Elegí una opción:"
        )

        botones = [
            {"type": "reply", "reply": {"id": "cupon_web", "title": "Tienda Web"}},
            {"type": "reply", "reply": {"id": "cupon_local", "title": "Local Físico"}},
        ]

        try:
            self.env['whatsapp.message'].sudo().create({
                'mobile_number': message.mobile_number,
                'body': texto,
                'state': 'outgoing',
                'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
                'interactive_type': 'button',
                'interactive_buttons': botones,
            })._send_message()
        except Exception as e:
            _logger.error("Error al enviar botones de regalo: %s", e)

    def _enviar_cupon(self, message, destino='web'):
        texto = "Tenés 3 días para usarlo, no te duermas. 😉"

        try:
            imagen_id = self.env['ir.attachment'].search([
                ('name', '=', 'cupon_web'),
                ('mimetype', 'ilike', 'image/%')
            ], limit=1)

            if not imagen_id:
                _logger.warning("No se encontró la imagen del cupón para enviar.")
                return

            self.env['whatsapp.message'].sudo().create({
                'mobile_number': message.mobile_number,
                'state': 'outgoing',
                'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
                'attachment_ids': [(4, imagen_id.id)],
                'body': texto,
            })._send_message()
        except Exception as e:
            _logger.error("Error al enviar cupón (%s): %s", destino, e)
