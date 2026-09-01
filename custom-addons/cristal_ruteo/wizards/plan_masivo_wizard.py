# -*- coding: utf-8 -*-
"""Configurar el plan de visitas para VARIOS clientes de una, con un popup.

Se selecciona un grupo (desde Contactos o desde la lista de oportunidades del
CRM), se abre este asistente y se elige frecuencia + día. Aplicás, y podés
repetir con otro grupo y otra configuración (5 los viernes quincenal, 4 los
martes semanal, etc.). El plan vive en el cliente, así que desde el CRM se
aplica sobre el contacto de cada oportunidad."""
from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.res_partner_visitas import VISIT_FREQ, VISIT_WEEKDAYS


class PlanMasivoWizard(models.TransientModel):
    _name = 'cristal.plan.masivo.wizard'
    _description = 'Configurar plan de visitas en masa'

    partner_ids = fields.Many2many(
        'res.partner', string="Clientes a configurar", required=True,
        help="Los clientes que van a quedar con esta configuración de visita.")
    partner_count = fields.Integer(
        string="Cantidad", compute='_compute_partner_count')
    user_id = fields.Many2one(
        'res.users', string="Vendedor", required=True,
        help="Quién visita a estos clientes. Es obligatorio: sin vendedor, el cliente "
             "no aparece en 'Mi día' (que filtra por 'Míos').")

    @api.model
    def default_get(self, fields_list):
        """Propone el vendedor que ya tienen los seleccionados; si no tienen, el usuario actual."""
        res = super().default_get(fields_list)
        if 'user_id' in fields_list and not res.get('user_id'):
            ids = []
            for cmd in (self.env.context.get('default_partner_ids') or []):
                if isinstance(cmd, (list, tuple)) and len(cmd) == 3 and cmd[0] == 6:
                    ids = cmd[2]
            users = [p.user_id.id for p in self.env['res.partner'].browse(ids) if p.user_id]
            res['user_id'] = max(set(users), key=users.count) if users else self.env.uid
        return res
    visit_frequency = fields.Selection(
        VISIT_FREQ, string="Frecuencia", required=True, default='quincenal')
    visit_weekday = fields.Selection(
        VISIT_WEEKDAYS, string="Día de la semana",
        help="Día en que se agenda la visita. Si lo dejás vacío, no fija un día fijo.")
    reprogramar = fields.Boolean(
        string="Reprogramar la próxima visita", default=True,
        help="Si está activo, recalcula la próxima visita desde hoy según el día "
             "elegido. Si lo desactivás, no toca la próxima visita de los que ya la tienen.")

    @api.depends('partner_ids')
    def _compute_partner_count(self):
        for wiz in self:
            wiz.partner_count = len(wiz.partner_ids)

    def action_apply(self):
        self.ensure_one()
        if not self.partner_ids:
            raise UserError("No hay clientes seleccionados para configurar.")
        today = fields.Date.context_today(self)
        for partner in self.partner_ids:
            vals = {
                'visit_plan_active': True,
                'visit_frequency': self.visit_frequency,
                'user_id': self.user_id.id,
            }
            if self.visit_weekday:
                vals['visit_weekday'] = self.visit_weekday
            partner.write(vals)
            if self.reprogramar or not partner.visit_next:
                partner.visit_next = partner._visit_first_date(today)
        freq_label = dict(VISIT_FREQ).get(self.visit_frequency, self.visit_frequency)
        dia_label = dict(VISIT_WEEKDAYS).get(self.visit_weekday, "sin día fijo")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Plan de visitas",
                'message': "%s cliente(s) configurados: %s · %s." % (
                    len(self.partner_ids), freq_label, dia_label),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
