# -*- coding: utf-8 -*-
"""1.81.1 — Ajustes del 24/11/2026 (Joaco, tras revisar el fin de semana largo).

- Cotizaciones abiertas a granel → bidones de 20 L con el mismo precio por litro.
- Guillermo ("Guille", el número del depósito) en No contactar: no es cliente.
- Trato de VOS reforzado al principio del prompt (seguía saliendo "usted").
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

MARK = "TRATO: SIEMPRE DE VOS"
BLOCK = (
    "## ⚠️ " + MARK + " (Joaco, 24/11/2026 — regla dura)\n"
    "Tratá a TODOS los clientes de VOS, también a los que te tratan de usted y en los "
    "chats donde antes se les habló de usted. Nunca \"le escribo\", \"su pedido\", \"le "
    "armé\", \"disculpe\", \"tiene razón\", \"don\": decí \"te escribo\", \"tu pedido\", "
    "\"te armé\", \"disculpá\", \"tenés razón\". Revisá cada mensaje antes de mandarlo.\n\n")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    staff_id = int(env['ir.config_parameter'].sudo().get_param(
        'cristal_agent.pickup_staff_partner_id', '0') or 0)
    staff = env['res.partner'].sudo().browse(staff_id).exists()
    if staff and not staff.agent_opt_out:
        staff.set_agent_opt_out("es Guillermo, del depósito (no es cliente)")

    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if config and config.system_prompt and MARK not in config.system_prompt:
        config.system_prompt = BLOCK + config.system_prompt

    try:
        changed = env['sale.order'].cristal_convert_granel_drafts()
        _logger.info("1.81.1: granel → bidones en %s cotizaciones", len(changed))
    except Exception:  # noqa: BLE001 — no frena la actualización
        _logger.exception("1.81.1: no pude pasar el granel a bidones")
