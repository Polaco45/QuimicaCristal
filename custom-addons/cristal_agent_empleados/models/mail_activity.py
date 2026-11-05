# -*- coding: utf-8 -*-
from odoo import models


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    def _action_done(self, feedback=False, attachment_ids=None):
        """Sergio marcó hecha la actividad de una consulta escalada: la nota que dejó va
        al empleado en el mismo registro."""
        if not self.env.context.get('cristal_employee_relayed'):
            escalations = self.env['cristal.agent.employee.escalation'].sudo().search([
                ('activity_id', 'in', self.ids), ('state', '=', 'open')])
            if escalations:
                escalations.relay(feedback or '', 'activity')
        return super()._action_done(feedback=feedback, attachment_ids=attachment_ids)
