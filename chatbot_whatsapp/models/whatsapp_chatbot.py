# -*- coding: utf-8 -*-
from odoo import models, api, _
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for message in records:
            if message.state == 'received' and message.mobile_number and message.body:
                user_text = message.body.strip().lower()
                if 'quiero mi regalo' in user_text:
                    self._send_template_gift(message)
                elif user_text in ['tienda web', 'local físico', 'local fisico']:
                    self._send_coupon_image(message)
        return records

    def _send_template_gift(self, message):
        try:
            self.env['whatsapp.message'].sudo().create({
                'mobile_number': message.mobile_number,
                'state': 'template',
                'template_name': 'promo_regalo_10000',
                'template_language': 'en',  # porque la plantilla está en inglés
                'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
            })._send_message()
            _logger.info("Plantilla enviada correctamente a %s", message.mobile_number)
        except Exception as e:
            _logger.error("Error al enviar plantilla de regalo: %s", e)

    def _send_coupon_image(self, message):
        try:
            attachment = self.env['ir.attachment'].sudo().search([
                ('name', '=', 'cupon_web'),
                ('public', '=', True)
            ], limit=1)

            if not attachment:
                _logger.warning("No se encontró la imagen pública 'cupon_web'.")
                return

            image_url = '/web/image/%s' % attachment.id
            full_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') + image_url

            coupon_text = "Tenés 3 días para usarlo, ¡no te duermas! 🎁"

            self.env['whatsapp.message'].sudo().create({
                'mobile_number': message.mobile_number,
                'body': coupon_text,
                'state': 'outgoing',
                'attachment_url': full_url,
                'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
            })._send_message()
            _logger.info("Cupón enviado correctamente a %s", message.mobile_number)
        except Exception as e:
            _logger.error("Error al enviar imagen de cupón: %s", e)
