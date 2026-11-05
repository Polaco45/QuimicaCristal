# -*- coding: utf-8 -*-
"""1.0.1: el prompt busca primero la respuesta en la orden (tacho/granel) antes de escalar."""
from odoo import SUPERUSER_ID, api

from odoo.addons.cristal_agent_empleados.models.agent_config import DEFAULT_EMPLOYEE_PROMPT


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['cristal.agent.config'].sudo().search([]).write({'system_prompt_employee': DEFAULT_EMPLOYEE_PROMPT})
