# -*- coding: utf-8 -*-
"""1.80.1 — El pedido para retirar se prepara EN EL DÍA (Joaco, 20/11/2026: "El mismo día")."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

OLD = ("- Al confirmar un retiro: \"Lo preparamos y te avisamos por WhatsApp cuando esté listo para "
       "retirar\" (no prometas hora).")
NEW = ("- Al confirmar un retiro: \"Lo preparamos en el día y te avisamos por WhatsApp cuando esté "
       "listo para retirar\" (no prometas hora exacta). Si lo pide fuera del horario o sobre el "
       "cierre, queda listo el siguiente día hábil.")
KB_ADD = (" El pedido se prepara EN EL DÍA (si lo pide fuera del horario o sobre el cierre, queda "
          "listo el siguiente día hábil); no se promete hora exacta.")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if config and config.system_prompt and OLD in config.system_prompt:
        config.system_prompt = config.system_prompt.replace(OLD, NEW)
    kb = env['cristal.agent.knowledge'].with_context(active_test=False).search(
        [('name', 'ilike', 'Retiro en el local con pedido previo')], limit=1)
    if kb and 'EN EL DÍA' not in (kb.content or ''):
        kb.content = (kb.content or '') + KB_ADD
    _logger.info("1.80.1: retiro en el día cargado en prompt=%s kb=%s", bool(config), kb.id if kb else None)
