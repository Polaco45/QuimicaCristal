# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _message_post_after_hook(self, message, msg_vals):
        """WhatsApp que manda un proveedor: lista → se guarda; respuesta → a su orden."""
        res = super()._message_post_after_hook(message, msg_vals)
        if self.channel_type == 'whatsapp' and message.message_type == 'whatsapp_message':
            partner = self.whatsapp_partner_id
            if partner and message.author_id == partner and partner.commercial_partner_id.supplier_rank > 0:
                try:
                    self.env['cristal.compras'].sudo().process_supplier_message(partner, message, 'whatsapp')
                except Exception:
                    _logger.exception("cristal_compras: no pude procesar el WhatsApp de %s", partner.name)
        return res
