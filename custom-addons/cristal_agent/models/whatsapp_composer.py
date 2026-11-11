# -*- coding: utf-8 -*-
"""
Política de envío de plantillas pagas también para los envíos automáticos que no
pasan por la tool (crons, acciones de servidor, empujes masivos por RPC).

Lo que manda una persona a mano desde Odoo NO se toca: la política corre solo
cuando el envío sale como OdooBot o con el contexto del agente.
"""
import logging
from odoo import models, SUPERUSER_ID
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WhatsappComposer(models.TransientModel):
    _inherit = 'whatsapp.composer'

    def _cristal_policy_block(self):
        """Motivo por el que NO conviene mandar esta plantilla, o None."""
        self.ensure_one()
        ctx = self.env.context
        if ctx.get('wa_policy_checked') or ctx.get('wa_policy_bypass'):
            return None
        if self.env.uid != SUPERUSER_ID and not ctx.get('from_cristal_agent'):
            return None
        template = self.wa_template_id
        if not template or not self.phone:
            return None
        text = ' '.join(str(self[f'free_text_{i}'] or '') for i in range(1, 11)
                        if f'free_text_{i}' in self._fields).strip()
        from ..services.helpers import wa_template_policy
        return wa_template_policy(self.env, self.phone, text, template)

    def action_send_whatsapp_template(self):
        if len(self) == 1:
            try:
                blocked = self._cristal_policy_block()
            except Exception:
                _logger.exception("Política de envío: error, se deja pasar")
                blocked = None
            if blocked:
                _logger.info("⏸️ Plantilla '%s' a %s NO enviada (%s)",
                             self.wa_template_id.template_name, self.phone, blocked['code'])
                raise UserError(f"NO ENVIADO ({blocked['code']}): {blocked['message']}")
        return super().action_send_whatsapp_template()
