# -*- coding: utf-8 -*-
"""Consultas de empleados en el chatter: cola con debounce y horario de respuesta."""
import logging
from datetime import timedelta

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

WORK_DAYS = range(0, 6)   # lunes a sábado


def parse_hours(spec):
    """'8-13,17-20' → [(8.0, 13.0), (17.0, 20.0)]."""
    windows = []
    for part in (spec or '').split(','):
        try:
            start, end = part.split('-')
            windows.append((float(start), float(end)))
        except ValueError:
            continue
    return sorted(windows) or [(8.0, 13.0), (17.0, 20.0)]


def next_opening(local_now, windows, tz):
    """Datetime local (con tz) en que se puede contestar: ahora si está en horario, si no
    el inicio de la próxima franja de lunes a sábado."""
    for add_days in range(0, 8):
        day = (local_now + timedelta(days=add_days)).date()
        if day.weekday() not in WORK_DAYS:
            continue
        for start, end in windows:
            start_dt = tz.localize(
                fields.Datetime.to_datetime(day).replace(hour=int(start), minute=int(round((start % 1) * 60))))
            end_dt = tz.localize(
                fields.Datetime.to_datetime(day).replace(hour=int(end), minute=int(round((end % 1) * 60))))
            if add_days == 0 and start_dt <= local_now < end_dt:
                return local_now
            if start_dt > local_now:
                return start_dt
    return local_now


class CristalAgentEmployeeQuestion(models.Model):
    _name = 'cristal.agent.employee.question'
    _description = "Cristal Agent — consulta de un empleado en el chatter"
    _order = 'create_date desc'

    res_model = fields.Char(string="Modelo", required=True, index=True)
    res_id = fields.Integer(string="ID", required=True, index=True)
    record_name = fields.Char(string="Registro")
    employee_partner_id = fields.Many2one('res.partner', string="Empleado", required=True)
    text = fields.Text(string="Lo que escribió")
    message_id = fields.Many2one('mail.message', string="Último mensaje")
    due_at = fields.Datetime(string="Se contesta a partir de", index=True)
    state = fields.Selection([('pending', "En cola"), ('done', "Contestada"), ('silent', "Sin respuesta"),
                              ('escalated', "Pasada a Sergio"), ('error', "Error")],
                             string="Estado", default='pending', required=True, index=True)
    response = fields.Text(string="Respuesta")
    run_id = fields.Many2one('cristal.agent.run', string="Corrida")
    error = fields.Text(string="Error")

    # ───────────────────────── Cola ─────────────────────────
    @api.model
    def _due_time(self, config):
        from odoo.addons.cristal_agent.services.helpers import tz_ar
        tz = tz_ar(self.env)
        local_now = pytz.utc.localize(fields.Datetime.now()).astimezone(tz)
        debounce = timedelta(seconds=config.debounce_seconds or 15)
        opening = next_opening(local_now, parse_hours(config.employee_hours), tz)
        due_local = max(opening, local_now + debounce)
        return due_local.astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def enqueue(self, record, author, message, text):
        """Suma el mensaje a la consulta en cola del mismo registro y empleado (ráfaga) o
        abre una nueva, y programa el cron para cuando toque contestar."""
        config = self.env['cristal.agent.config'].sudo().get_active()
        due = self._due_time(config)
        pending = self.sudo().search([('res_model', '=', record._name), ('res_id', '=', record.id),
                                      ('employee_partner_id', '=', author.id), ('state', '=', 'pending')],
                                     limit=1)
        if pending:
            pending.write({'text': f"{pending.text}\n{text}", 'message_id': message.id, 'due_at': due})
            question = pending
        else:
            question = self.sudo().create({
                'res_model': record._name, 'res_id': record.id, 'record_name': record.display_name,
                'employee_partner_id': author.id, 'text': text, 'message_id': message.id, 'due_at': due,
            })
        cron = self.env.ref('cristal_agent_empleados.cron_process_employee_questions', raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger(at=due + timedelta(seconds=1))
        return question

    @api.model
    def cron_process(self):
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config or not config.employee_mode_enabled:
            return
        due = self.sudo().search([('state', '=', 'pending'), ('due_at', '<=', fields.Datetime.now())],
                                 order='due_at, id', limit=20)
        from ..services.employee_agent import answer_question
        for question in due:
            try:
                answer_question(self.env, question)
            except Exception as e:
                _logger.exception("Asistente de empleados: falló la consulta %s", question.id)
                question.write({'state': 'error', 'error': str(e)[:2000]})
            if not getattr(threading_current(), 'testing', False):
                self.env.cr.commit()

    def record(self):
        self.ensure_one()
        return self.env[self.res_model].sudo().browse(self.res_id).exists()

    @api.model
    def turns_today(self, record):
        from odoo.addons.cristal_agent.services.helpers import tz_ar
        tz = tz_ar(self.env)
        local_midnight = pytz.utc.localize(fields.Datetime.now()).astimezone(tz).replace(
            hour=0, minute=0, second=0, microsecond=0)
        since = local_midnight.astimezone(pytz.utc).replace(tzinfo=None)
        return self.sudo().search_count([('res_model', '=', record._name), ('res_id', '=', record.id),
                                         ('state', 'in', ['done', 'escalated']),
                                         ('write_date', '>=', since)])


def threading_current():
    import threading
    return threading.current_thread()
