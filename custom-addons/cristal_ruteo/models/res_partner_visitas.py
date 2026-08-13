# -*- coding: utf-8 -*-
"""
Plan de visitas manual — vive en la FICHA DEL CLIENTE (res.partner).

La regla (frecuencia + día) es del cliente y lo acompaña toda la vida: prospecto
→ cliente → recurrente. Ganar una oportunidad NO corta las visitas; el propósito
de la visita lo deduce el CRM (se reusa `ruteo_visit_type`: captación/cierre/
reposición/reactivación). Rústico: sin geolocalización ni ruteo automático.
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

# Resultado de la visita (registro de un toque).
VISIT_OUTCOMES = [
    ('compro', 'Compró / hizo pedido'),
    ('cotizo', 'Pidió cotización'),
    ('dejo_muestra', 'Dejó muestra'),
    ('no_estaba', 'No estaba / cerrado'),
    ('sin_interes', 'Sin interés'),
    ('otro', 'Otro'),
]


class ResPartner(models.Model):
    _inherit = 'res.partner'

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
        string="Le toca hoy", compute='_compute_visit_is_today',
        search='_search_visit_is_today')
    visit_day_order = fields.Integer(
        string="Orden del día", default=10, copy=False,
        help="Orden en que la vendedora recorre el día (arrastrar arriba/abajo).")
    visit_objetivo = fields.Char(
        string="Objetivo", compute='_compute_visit_objetivo',
        help="Qué hacer en esta visita, deducido del CRM.")
    visit_dias_sin_comprar = fields.Integer(
        related='agent_days_since_last_purchase', string="Días sin comprar")

    def _compute_visit_objetivo(self):
        for partner in self:
            partner.visit_objetivo = partner._ruteo_visit_reason()

    @api.depends('visit_frequency')
    def _compute_visit_frequency_days(self):
        for partner in self:
            partner.visit_frequency_days = VISIT_FREQ_DAYS.get(partner.visit_frequency, 15)

    @api.depends('visit_next', 'visit_plan_active')
    def _compute_visit_is_today(self):
        today = fields.Date.context_today(self)
        for partner in self:
            partner.visit_is_today = bool(
                partner.visit_plan_active and partner.visit_next and partner.visit_next <= today)

    def _search_visit_is_today(self, operator, value):
        today = fields.Date.context_today(self)
        domain = ['&', ('visit_plan_active', '=', True), ('visit_next', '<=', today)]
        if (operator == '=' and not value) or (operator == '!=' and value):
            return ['!'] + domain
        return domain

    # ─────────── Helpers de fechas ───────────
    def _visit_next_from(self, base_date):
        self.ensure_one()
        days = VISIT_FREQ_DAYS.get(self.visit_frequency, 15)
        d = base_date + timedelta(days=days)
        if self.visit_weekday:
            d += timedelta(days=(int(self.visit_weekday) - d.weekday()) % 7)
        return d

    def _visit_first_date(self, from_date):
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
                _logger.exception("Visitas: no se pudo cerrar actividad de %s", self.display_name)
        if next_date:
            try:
                self.env['mail.activity'].create({
                    'res_model_id': self.env['ir.model']._get_id('res.partner'),
                    'res_id': self.id,
                    'activity_type_id': vtype.id,
                    'date_deadline': next_date,
                    'summary': 'Visitar',
                    'user_id': self.user_id.id or self.env.uid,
                })
            except Exception:  # noqa: BLE001
                _logger.exception("Visitas: no se pudo agendar próxima de %s", self.display_name)

    # ─────────── Acciones ───────────
    def _visit_log(self, action_type, note=None, outcome=None):
        """Deja el asiento en el registro de control (siempre, vía sudo)."""
        self.ensure_one()
        self.env['cristal.visita.log'].sudo().create({
            'partner_id': self.id,
            'visit_date': fields.Date.context_today(self),
            'user_id': self.user_id.id or self.env.uid,
            'action_type': action_type,
            'visit_type': self.ruteo_visit_type,
            'outcome': outcome or False,
            'note': note or False,
            'lead_id': self._ruteo_best_open_lead().id or False,
        })

    def _visit_register_done(self, note=None, outcome=None):
        today = fields.Date.context_today(self)
        outcome_label = dict(VISIT_OUTCOMES).get(outcome or '', '')
        for partner in self:
            if outcome == 'no_estaba':
                # No se pudo visitar: reprograma pronto, no cuenta como visita hecha.
                nxt = today + timedelta(days=3)
                partner.visit_next = nxt
                body = "🚪 <b>No estaba</b> — %s. Reprogramada al %s" % (
                    fields.Date.to_string(today), fields.Date.to_string(nxt))
                if note:
                    body += "<br/>%s" % note
                partner.message_post(body=body)
                partner._visit_log('visita', note=note, outcome=outcome)
                continue
            nxt = partner._visit_next_from(today)
            partner.write({'visit_last': today, 'visit_next': nxt, 'visit_plan_active': True})
            body = "🚗 <b>Visita realizada</b> — %s%s" % (
                fields.Date.to_string(today),
                (" · %s" % outcome_label) if outcome_label else "")
            if note:
                body += "<br/>%s" % note
            partner.message_post(body=body)
            partner._visit_close_and_reschedule(nxt)
            partner._visit_log('visita', note=note, outcome=outcome)
        return True

    def _visit_postpone(self, new_date, reason=None):
        for partner in self:
            old = partner.visit_next
            partner.visit_next = new_date
            body = "🔁 <b>Visita pospuesta</b> — %s → %s" % (
                fields.Date.to_string(old) if old else '?', fields.Date.to_string(new_date))
            if reason:
                body += " (%s)" % reason
            partner.message_post(body=body)
            partner._visit_close_and_reschedule(new_date)
            partner._visit_log('posposicion', note=reason)
        return True

    def action_visit_schedule(self):
        today = fields.Date.context_today(self)
        for partner in self:
            partner.visit_plan_active = True
            if not partner.visit_next:
                partner.visit_next = partner._visit_first_date(today)
            partner._visit_close_and_reschedule(partner.visit_next)
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
            'context': {'default_partner_id': self.id, 'default_modo': modo},
        }
