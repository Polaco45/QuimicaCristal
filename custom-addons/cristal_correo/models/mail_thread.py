# -*- coding: utf-8 -*-
"""Mail a una dirección de la empresa sin alias en Odoo: a la Bandeja general, no rebota."""
import ast
import logging

from odoo import api, models
from odoo.tools import email_split

_logger = logging.getLogger(__name__)

COMPANY_DOMAIN = 'quimicacristal.com.ar'
FALLBACK_ALIAS = 'bandeja'          # bandeja@ → proyecto "Bandeja general"
AUTO_PRECEDENCE = ('bulk', 'junk', 'list', 'auto_reply')


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    @api.model
    def message_route(self, message, message_dict, model=None, thread_id=None, custom_values=None):
        """Sergio (03/11): lo que llega a cualquier dirección @quimicacristal.com.ar y no
        coincide con ningún alias entra a la Bandeja general en vez de rebotar, salvo
        rebotes y respuestas automáticas (esos siguen el camino normal de Odoo)."""
        try:
            return super().message_route(message, message_dict, model=model, thread_id=thread_id,
                                         custom_values=custom_values)
        except ValueError:
            route = self._cristal_fallback_route(message, message_dict)
            if not route:
                raise
            _logger.info("Routing mail from %s to %s with Message-Id %s: sin alias, a la Bandeja general",
                         message_dict.get('email_from'), message_dict.get('to'),
                         message_dict.get('message_id'))
            return route

    @api.model
    def _cristal_fallback_route(self, message, message_dict):
        recipients = email_split(' '.join(str(message_dict.get(k) or '')
                                          for k in ('to', 'cc', 'recipients')))
        if not any(r.lower().endswith('@' + COMPANY_DOMAIN) for r in recipients):
            return []
        if self._cristal_is_automatic(message, message_dict):
            return []
        alias = self.env['mail.alias'].sudo().search(
            [('alias_name', '=', FALLBACK_ALIAS), ('alias_domain_id.name', '=', COMPANY_DOMAIN)], limit=1)
        if not alias or not alias.alias_model_id:
            return []
        email_from = message_dict.get('email_from') or ''
        user_id = self._mail_find_user_for_gateway(email_from, alias=alias).id or self._uid
        route = (alias.alias_model_id.model, alias.alias_force_thread_id,
                 ast.literal_eval(alias.alias_defaults or '{}'), user_id, alias)
        return [route] if self._routing_check_route(message, message_dict, route, raise_exception=False) else []

    @api.model
    def _cristal_is_automatic(self, message, message_dict):
        """Rebotes, acuses y respuestas automáticas: no van a la bandeja."""
        if message.get_content_type() == 'multipart/report':
            return True
        auto = (message.get('Auto-Submitted') or '').strip().lower()
        if auto and auto != 'no':
            return True
        if (message.get('Precedence') or '').strip().lower() in AUTO_PRECEDENCE:
            return True
        if message.get('X-Autoreply') or message.get('X-Autorespond'):
            return True
        return self.env['cristal.mail.account']._is_automatic_sender(message_dict.get('email_from'))
