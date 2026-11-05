# -*- coding: utf-8 -*-
import logging

from odoo import models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    def _message_post_after_hook(self, message, msg_vals):
        res = super()._message_post_after_hook(message, msg_vals)
        if self._name == 'discuss.channel' or len(self) != 1 \
                or self.env.context.get('cristal_employee_bot') or self.env.context.get('from_cristal_agent'):
            return res
        if message.message_type != 'comment' or not message.author_id:
            return res
        try:
            self._cristal_employee_dispatch(message)
        except Exception:
            _logger.exception("Asistente de empleados: no pude procesar el mensaje %s", message.id)
        return res

    def _cristal_employee_dispatch(self, message):
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config or not config.enabled or not config.employee_mode_enabled:
            return
        author = message.author_id
        text = html2plaintext(message.body or '').strip()
        if not text:
            return   # solo tracking o adjunto sin texto
        sergio_partner = config.sergio_user_id.partner_id
        if sergio_partner and author == sergio_partner:
            # Sergio contestó en el chatter de un registro con una consulta escalada.
            escalations = self.env['cristal.agent.employee.escalation'].sudo().search([
                ('res_model', '=', self._name), ('res_id', '=', self.id), ('state', '=', 'open')])
            if escalations:
                escalations.relay(message.body, 'chatter')
            return
        if author not in config.employee_partner_ids:
            return
        if config.bot_partner_id and author == config.bot_partner_id:
            return
        domain = [('res_model', '=', self._name), ('res_id', '=', self.id)]
        if author.user_ids:
            domain.append(('user_id', 'in', author.user_ids.ids))
        if not self.env['mail.activity'].sudo().search_count(domain):
            return   # sin actividad abierta suya en este registro: no es para Claudio
        self.env['cristal.agent.employee.question'].enqueue(self, author, message, text)
