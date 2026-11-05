# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

EMPLOYEE_PARTNERS = [65371, 436]   # Guillermo, Adrián (spec de Sergio, 05/11)
SERGIO_USER = 2
SERGIO_PARTNER = 3
BOT_WA_ACCOUNT_NAME = 'Cristal Mayorista'


def post_init_hook(env):
    config = env['cristal.agent.config'].sudo().get_active()
    if not config:
        return
    partners = env['res.partner'].sudo().browse(EMPLOYEE_PARTNERS).exists()
    vals = {'employee_partner_ids': [(6, 0, partners.ids)]}
    sergio = env['res.users'].sudo().browse(SERGIO_USER).exists()
    if sergio:
        vals['sergio_user_id'] = sergio.id
    sergio_partner = env['res.partner'].sudo().browse(SERGIO_PARTNER).exists()
    if sergio_partner:
        vals['sergio_whatsapp_partner_id'] = sergio_partner.id
    account = env['whatsapp.account'].sudo().search([('name', '=', BOT_WA_ACCOUNT_NAME)], limit=1)
    if account:
        vals['employee_wa_account_id'] = account.id
    config.write(vals)
    _logger.info("cristal_agent_empleados: empleados %s, Sergio %s, cuenta %s",
                 partners.mapped('name'), sergio.name, account.name)
    # Si Sergio contesta por WhatsApp al aviso, el bot de ventas no tiene que atenderlo
    # como si fuera un cliente: queda en takeover indefinido (el bot no le responde).
    if sergio_partner:
        try:
            memory = env['cristal.agent.memory'].sudo().get_or_create(sergio_partner)
            if not memory.human_takeover:
                memory.activate_takeover(reason="Sergio: avisos internos del asistente de empleados",
                                         duration_hours=0)
        except Exception:
            _logger.exception("cristal_agent_empleados: no pude pausar el bot para Sergio")
