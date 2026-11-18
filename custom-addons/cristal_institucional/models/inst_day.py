from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError

TZ = 'America/Argentina/Cordoba'


def _previous_workday(day):
    prev = day - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev


class CristalInstDay(models.Model):
    _name = 'cristal.inst.day'
    _description = 'Institucional: mi día'
    _order = 'date desc, id desc'
    _rec_name = 'date'

    date = fields.Date('Día', required=True, index=True, default=fields.Date.context_today)
    user_id = fields.Many2one('res.users', 'Quién', required=True, index=True,
                              default=lambda self: self.env.user)
    state = fields.Selection([('open', 'En curso'), ('closed', 'Cerrado')], 'Estado', default='open')
    target = fields.Integer('Objetivo de contactos', default=15)

    # Hoy
    calls = fields.Integer('Llamadas y mensajes hechos', compute='_compute_progress')
    contacts = fields.Integer('Contactos logrados', compute='_compute_progress')
    progress = fields.Integer('Avance del día (%)', compute='_compute_progress')
    missing = fields.Integer('Te faltan', compute='_compute_progress')
    pending = fields.Integer('Quedan en la lista', compute='_compute_leads')
    lead_ids = fields.Many2many('crm.lead', string='Para hoy', compute='_compute_leads')
    met = fields.Boolean('Objetivo cumplido', compute='_compute_progress')
    headline = fields.Char('Cómo venís', compute='_compute_progress')

    # Semana
    week_contacts = fields.Integer('Contactos de la semana', compute='_compute_week')
    week_target = fields.Integer('Objetivo semanal de contactos', compute='_compute_week')
    week_progress = fields.Integer('Avance de la semana (%)', compute='_compute_week')
    week_kits = fields.Integer('Kits aceptados en la semana', compute='_compute_week')
    week_kits_target = fields.Integer('Objetivo semanal de kits', compute='_compute_week')
    week_kits_progress = fields.Integer('Avance de kits (%)', compute='_compute_week')
    week_first_orders = fields.Integer('Primeras compras de la semana', compute='_compute_week')
    week_reorders = fields.Integer('Segundos pedidos de la semana', compute='_compute_week')
    streak = fields.Integer('Días seguidos cumpliendo', compute='_compute_week')

    # Cierre
    explanation = fields.Text(
        'Qué pasó hoy',
        help='Si no llegaste al objetivo, contá por qué. Sin esto el día no se puede cerrar.')
    closed_at = fields.Datetime('Cerrado el', readonly=True)
    blocked_by_previous = fields.Boolean('Hay un día anterior sin cerrar', compute='_compute_blocked')

    _sql_constraints = [
        ('day_user_uniq', 'unique(date, user_id)', 'Ya existe el día para este usuario.'),
    ]

    # ------------------------------------------------------------- cálculos
    def _bounds(self, start_day, end_day):
        tz = pytz.timezone(self.env.user.tz or TZ)
        start = tz.localize(datetime.combine(start_day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        end = tz.localize(datetime.combine(end_day + timedelta(days=1), time.min)).astimezone(
            pytz.utc).replace(tzinfo=None)
        return start, end

    def _calls(self, start_day, end_day):
        self.ensure_one()
        start, end = self._bounds(start_day, end_day)
        return self.env['cristal.inst.call'].sudo().search([
            ('user_id', '=', self.user_id.id), ('date', '>=', start), ('date', '<', end)])

    @api.depends('date', 'user_id', 'target')
    def _compute_progress(self):
        for day in self:
            calls = day._calls(day.date, day.date) if day.date and day.user_id else self.env['cristal.inst.call']
            contacts = len(calls.filtered(lambda c: c.result != 'no_atendio'))
            target = max(1, day.target or 1)
            day.calls = len(calls)
            day.contacts = contacts
            day.progress = min(100, round(100 * contacts / target))
            day.missing = max(0, target - contacts)
            day.met = contacts >= target
            if day.met:
                day.headline = 'Objetivo cumplido: %s contactos de %s.' % (contacts, target)
            elif contacts:
                day.headline = 'Vas %s de %s. Te faltan %s.' % (contacts, target, target - contacts)
            else:
                day.headline = 'Todavía no registraste contactos. El objetivo de hoy es %s.' % target

    @api.depends('date', 'user_id')
    def _compute_leads(self):
        Lead = self.env['crm.lead'].sudo()
        for day in self:
            leads = Lead.search([
                ('inst_account', '=', True), ('inst_today', '=', True),
                '|', ('user_id', '=', day.user_id.id), ('user_id', '=', False),
            ], order='inst_priority desc')
            day.lead_ids = leads
            day.pending = len(leads)

    @api.depends('date', 'user_id', 'target')
    def _compute_week(self):
        icp = self.env['ir.config_parameter'].sudo()
        try:
            kits_target = int(icp.get_param('cristal_institucional.weekly_kits', 15))
        except (TypeError, ValueError):
            kits_target = 15
        Log = self.env['cristal.inst.stage.log'].sudo()
        for day in self:
            if not day.date or not day.user_id:
                day.week_contacts = day.week_target = day.week_progress = 0
                day.week_kits = day.week_kits_target = day.week_kits_progress = 0
                day.week_first_orders = day.week_reorders = day.streak = 0
                continue
            monday = day.date - timedelta(days=day.date.weekday())
            calls = day._calls(monday, day.date)
            day.week_contacts = len(calls.filtered(lambda c: c.result != 'no_atendio'))
            day.week_target = (day.target or 15) * 5
            day.week_progress = min(100, round(100 * day.week_contacts / max(1, day.week_target)))
            day.week_kits = len(calls.filtered(lambda c: c.result == 'kit'))
            day.week_kits_target = kits_target
            day.week_kits_progress = min(100, round(100 * day.week_kits / max(1, kits_target)))
            logs = Log.search([('date', '>=', monday), ('date', '<=', day.date), ('stage_from', '!=', False)])
            day.week_first_orders = len(logs.filtered(lambda l: l.stage_to == 'pedido_formal'
                                                      and l.stage_from != 'recurrente'))
            day.week_reorders = len(logs.filtered(lambda l: l.stage_to == 'recurrente'
                                                  and l.stage_from == 'pedido_formal'))
            streak = 0
            previous = self.search([('user_id', '=', day.user_id.id), ('date', '<', day.date)],
                                   order='date desc', limit=60)
            for other in previous:
                if other.met:
                    streak += 1
                else:
                    break
            day.streak = streak + (1 if day.met else 0)

    @api.depends('date', 'user_id', 'state')
    def _compute_blocked(self):
        for day in self:
            day.blocked_by_previous = bool(day.date and self.search_count([
                ('user_id', '=', day.user_id.id), ('date', '<', day.date), ('state', '=', 'open')], limit=1))

    # ------------------------------------------------------------- acciones
    @api.model
    def _target(self):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param('cristal_institucional.daily_calls', 15))
        except (TypeError, ValueError):
            return 15

    def _open(self, title='Mi día'):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'cristal.inst.day',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def action_open_today(self):
        """Abre el día de hoy. Si quedó un día anterior sin cerrar, primero hay que cerrarlo."""
        user = self.env.user
        today = fields.Date.context_today(self)
        pending = self.search([('user_id', '=', user.id), ('date', '<', today), ('state', '=', 'open')],
                              order='date', limit=1)
        if pending:
            return pending._open('Cerrá primero el día anterior')
        day = self.search([('user_id', '=', user.id), ('date', '=', today)], limit=1)
        if not day:
            day = self.create({'user_id': user.id, 'date': today, 'target': self._target()})
        return day._open()

    def action_more(self):
        """Trae a la lista de hoy las cinco cuentas que siguen en prioridad."""
        self.ensure_one()
        if self.state == 'closed':
            raise UserError('Este día ya está cerrado.')
        Engine = self.env['cristal.inst.engine']
        added = Engine._pull_more(5)
        if not added:
            raise UserError('No hay más cuentas en la fila.')
        return True

    def action_close(self):
        self.ensure_one()
        if not self.met and not (self.explanation or '').strip():
            raise UserError(
                'Hoy lograste %s contactos de %s. Para cerrar el día sin cumplir el objetivo, '
                'escribí en "Qué pasó hoy" por qué no llegaste.' % (self.contacts, self.target))
        self.write({'state': 'closed', 'closed_at': fields.Datetime.now()})
        return self.action_open_today() if self.date < fields.Date.context_today(self) else True

    def action_reopen(self):
        self.write({'state': 'open', 'closed_at': False})
        return True
