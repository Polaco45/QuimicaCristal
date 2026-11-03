# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    def _message_post_after_hook(self, message, msg_vals):
        """Mail de un proveedor a una bandeja (compras@): las listas se guardan solas."""
        res = super()._message_post_after_hook(message, msg_vals)
        if message.message_type == 'email' and message.author_id \
                and message.author_id.commercial_partner_id.supplier_rank > 0:
            try:
                self.env['cristal.compras'].sudo().process_supplier_message(
                    message.author_id, message, 'mail')
            except Exception:
                _logger.exception("cristal_compras: no pude procesar el mail de %s", message.author_id.name)
        return res
