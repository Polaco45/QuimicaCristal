# -*- coding: utf-8 -*-
from odoo import fields, models


class CristalAgentRun(models.Model):
    _inherit = 'cristal.agent.run'

    trigger = fields.Selection(
        selection_add=[('employee_question', 'Consulta de un empleado (chatter)')],
        ondelete={'employee_question': 'set default'})
    employee_res_model = fields.Char(string="Modelo del registro (empleado)")
    employee_res_id = fields.Integer(string="ID del registro (empleado)")
