# -*- coding: utf-8 -*-
"""
Plan de visitas manual — vive en la oportunidad (crm.lead).

Regla simple por cliente (frecuencia + día) → el calendario se arma solo desde
la 'próxima visita'. El vendedor organiza a mano (Mi día), pospone, y al cerrar
registra en la nota interna con fecha, marca la actividad hecha y se agenda la
próxima. Rústico: sin geolocalización ni ruteo automático.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

VISIT_FREQ = [
    ('semanal', 'Semanal'),
    ('quincenal', 'Quincenal (cada 15 días)'),
    ('mensual', 'Mensual'),
]
VISIT_FREQ_DAYS = {'semanal': 7, 'quincenal': 15, 'mensual': 30}
VISIT_WEEKDAYS = [
    ('0', 'Lunes'), ('1', 'Martes'), ('2', 'Miércoles'),
    ('3', 'Jueves'), ('4', 'Viernes'),
]


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    visit_plan_active = fields.Boolean(
        string="En plan de visita", index=True, tracking=True,
        help="Si está marcado, este cliente entra al calendario de visitas.")
    visit_frequency = fields.Selection(
        VISIT_FREQ, string="Frecuencia de visita", default='quincenal')
    visit_weekday = fields.Selection(VISIT_WEEKDAYS, string="Día de visita")
    visit_last = fields.Date(string="Última visita", copy=False, tracking=True)
    visit_next = fields.Date(
        string="Próxima visita", index=True, copy=False, tracking=True,
        help="Fecha en que aparece en el calendario y en 'Mi día'. Editable a mano.")
    visit_frequency_days = fields.Integer(
        string="Frecuencia (días)", compute='_compute_visit_frequency_days', store=True)
    visit_is_today = fields.Boolean(
        string="Le toca hoy", compute='_compute_visit_is_today', search='_search_visit_is_today')

    @api.depends('visit_frequency')
    def _compute_visit_frequency_days(self):
        for lead in self:
            lead.visit_frequency_days = VISIT_FREQ_DAYS.get(lead.visit_frequency, 15)

    @api.depends('visit_next')
    def _compute_visit_is_today(self):
        today = fields.Date.context_today(self)
        for lead in self:
            lead.visit_is_today = bool(lead.visit_next and lead.visit_next <= today
                                       and lead.visit_plan_active)

    def _search_visit_is_today(self, operator, value):
        today = fields.Date.context_today(self)
        domain = ['&', ('visit_plan_active', '=', True), ('visit_next', '<=', today)]
        if (operator == '=' and not value) or (operator == '!=' and value):
            return ['!'] + domain
        return domain

    # ─────────── Helpers ───────────
    def _visit_next_from(self, base_date):
        """Próxima fecha = base + frecuencia, alineada al día de la semana elegido."""
        self.ensure_one()
        days = VISIT_FREQ_DAYS.get(self.visit_frequency, 15)
        d = base_date + timedelta(days=days)
        if self.visit_weekday:
            d += timedelta(days=(int(self.visit_weekday) - d.weekday()) % 7)
        return d

    def _visit_first_date(self, from_date):
        """Primera visita = próxima ocurrencia del día elegido (o hoy si no hay día)."""
        self.ensure_one()
        if self.visit_weekday:
            return from_date + timedelta(days=(int(self.visit_weekday) - from_date.weekday()) % 7)
        return from_date

    def _visit_activity_type(self):
        AT = self.env['mail.activity.type']
        return (AT.search([('name', 'ilike', 'Visitar')], limit=1)
                or AT.search([('category', '=', 'meeting')], limit=1)
                or AT.search([], limit=1))

    def _visit_close_and_reschedule(self, next_date):
        """Marca hecha la actividad de visita pendiente y agenda la próxima."""
        self.ensure_one()
        vtype = self._visit_activity_type()
        if not vtype:
            return
        pending = self.activity_ids.filtered(lambda a: a.activity_type_id == vtype)
        for act in pending:
            try:
                act.action_feedback(feedback="Visita registrada")
            except Exception:  # noqa: BLE001
                _logger.exception("Visitas: no se pudo cerrar la actividad de %s", self.display_name)
        if next_date:
            try:
                self.env['mail.activity'].create({
                    'res_model_id': self.env['ir.model']._get_id('crm.lead'),
                    'res_id': self.id,
                    'activity_type_id': vtype.id,
                    'date_deadline': next_date,
                    'summary': 'Visitar',
                    'user_id': self.user_id.id or self.env.uid,
                })
            except Exception:  # noqa: BLE001
                _logger.exception("Visitas: no se pudo agendar la próxima de %s", self.display_name)

    # ─────────── Acciones ───────────
    def _visit_register_done(self, note=None):
        today = fields.Date.context_today(self)
        for lead in self:
            nxt = lead._visit_next_from(today)
            lead.write({'visit_last': today, 'visit_next': nxt, 'visit_plan_active': True})
            body = "🚗 <b>Visita realizada</b> — %s" % fields.Date.to_string(today)
            if note:
                body += "<br/>%s" % note
            lead.message_post(body=body)
            lead._visit_close_and_reschedule(nxt)
        return True

    def _visit_postpone(self, new_date, reason=None):
        for lead in self:
            old = lead.visit_next
            lead.visit_next = new_date
            body = "🔁 <b>Visita pospuesta</b> — %s → %s" % (
                fields.Date.to_string(old) if old else '?', fields.Date.to_string(new_date))
            if reason:
                body += " (%s)" % reason
            lead.message_post(body=body)
            lead._visit_close_and_reschedule(new_date)
        return True

    def action_visit_schedule(self):
        """Programa la visita: fija la próxima si falta y agenda la actividad."""
        today = fields.Date.context_today(self)
        for lead in self:
            lead.visit_plan_active = True
            if not lead.visit_next:
                lead.visit_next = lead._visit_first_date(today)
            lead._visit_close_and_reschedule(lead.visit_next)
        return True

    def action_visit_done_wizard(self):
        self.ensure_one()
        return self._visit_open_wizard('done')

    def action_visit_postpone_wizard(self):
        self.ensure_one()
        return self._visit_open_wizard('posponer')

    def _visit_open_wizard(self, modo):
        return {
            'type': 'ir.actions.act_window',
            'name': "Visité hoy" if modo == 'done' else "Posponer visita",
            'res_model': 'cristal.visita.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.id, 'default_modo': modo},
        }
