from odoo import models, api
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super(WhatsAppMessage, self).create(vals_list)
        for message in records:
            if message.state == 'received' and message.body:
                texto = message.body.strip().lower()
                if 'quiero mi regalo' in texto:
                    try:
                        self.env['whatsapp.message'].sudo().create({
                            'mobile_number': message.mobile_number,
                            'template_id': 188,  # ID de la plantilla promo_regalo_10000
                            'state': 'outgoing',
                            'wa_account_id': message.wa_account_id.id,
                        })
                        _logger.info("Plantilla promo_regalo_10000 enviada a %s", message.mobile_number)
                    except Exception as e:
                        _logger.error("Error al enviar la plantilla: %s", e)
        return records
