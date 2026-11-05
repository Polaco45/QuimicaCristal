# -*- coding: utf-8 -*-
"""Consultas de empleados que se le pasan a Sergio, y el reenvío de su respuesta."""
import logging

from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

ALERT_TEMPLATE = 'cristal_aviso_interno'   # "Hola {{1}}, {{2}} te consulta: {{3}}. Contestale en Odoo."


class CristalAgentEmployeeEscalation(models.Model):
    _name = 'cristal.agent.employee.escalation'
    _description = "Cristal Agent — consulta de un empleado pasada a Sergio"
    _order = 'create_date desc'

    res_model = fields.Char(string="Modelo", required=True, index=True)
    res_id = fields.Integer(string="ID", required=True, index=True)
    record_name = fields.Char(string="Registro")
    employee_partner_id = fields.Many2one('res.partner', string="Empleado", required=True)
    question = fields.Text(string="Consulta", required=True)
    activity_id = fields.Many2one('mail.activity', string="Actividad de Sergio", ondelete='set null')
    state = fields.Selection([('open', "Esperando a Sergio"), ('answered', "Respondida")],
                             string="Estado", default='open', required=True, index=True)
    answer = fields.Text(string="Respuesta de Sergio")
    whatsapp_note = fields.Char(string="WhatsApp a Sergio")

    def record(self):
        self.ensure_one()
        return self.env[self.res_model].sudo().browse(self.res_id).exists()

    # ───────────────────────── Crear ─────────────────────────
    @api.model
    def escalate(self, record, employee, question, summary, run=None):
        config = self.env['cristal.agent.config'].sudo().get_active()
        sergio = config.sergio_user_id or self.env['res.users'].sudo().browse(2)
        first = (employee.name or '').split(' ')[0]
        summary = (summary or question or '').strip().replace('\n', ' ')
        own = self.env['mail.activity'].sudo().search([
            ('res_model', '=', record._name), ('res_id', '=', record.id),
            ('user_id', 'in', employee.user_ids.ids or [0])])
        original = "; ".join(f"{a.summary or a.activity_type_id.name} (vence {a.date_deadline})" for a in own)
        link = f"/odoo/{record._name}/{record.id}"
        note = (Markup("<p><b>%s pregunta:</b> %s</p><p>Actividad: %s</p>"
                       "<p>Contestá en el chatter de <a href='%s'>%s</a> (o marcá esta actividad "
                       "como hecha con la respuesta) y Claudio se la pasa.</p>")
                % (first, question, original or "—", link, record.display_name))
        activity = self.env['mail.activity'].sudo().create({
            'res_model_id': self.env['ir.model'].sudo()._get_id(record._name),
            'res_id': record.id,
            'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
            'user_id': sergio.id,
            'summary': f"Consulta de {first}: {summary}"[:180],
            'note': note,
            'date_deadline': fields.Date.context_today(self),
        })
        escalation = self.sudo().create({
            'res_model': record._name, 'res_id': record.id, 'record_name': record.display_name,
            'employee_partner_id': employee.id, 'question': question, 'activity_id': activity.id,
        })
        escalation.whatsapp_note = escalation._whatsapp_sergio(first, question, run=run)
        return escalation

    def _whatsapp_sergio(self, first, question, run=None):
        """Dentro de las 24 h, texto libre por la cuenta del bot; fuera, la plantilla
        «cristal_aviso_interno» si está aprobada. Si no se puede, le queda la actividad."""
        self.ensure_one()
        config = self.env['cristal.agent.config'].sudo().get_active()
        partner = config.sergio_whatsapp_partner_id
        account = config.employee_wa_account_id
        mobile = partner.mobile or partner.phone if partner else False
        if not (partner and account and mobile):
            return "no salió: falta el WhatsApp de Sergio o la cuenta en la configuración"
        text = f"{first} te consulta sobre {self.record_name}: {question}"[:900]
        try:
            from odoo.addons.cristal_agent.services.helpers import is_24h_window_open
            is_open, _last = is_24h_window_open(self.env, partner, wa_account_id=account.id)
        except Exception:
            is_open = False
        if is_open:
            channel = self.env['discuss.channel'].sudo().search([
                ('channel_type', '=', 'whatsapp'), ('wa_account_id', '=', account.id),
                ('channel_partner_ids', 'in', [partner.id])], order='write_date desc', limit=1)
            if channel:
                from odoo.addons.cristal_agent.services.tool_registry import ToolRegistry
                from odoo.addons.cristal_agent.services import tools  # noqa: F401 (registra las tools)
                tool = ToolRegistry.get('send_whatsapp')
                res = tool.execute(env=self.env, run=run, channel_id=channel.id,
                                   body=f"<p>{Markup.escape(text)} (contestale en Odoo)</p>",
                                   wa_account_id=account.id, mobile_number=mobile)
                if not res.get('error'):
                    return "texto libre (ventana abierta)"
                _logger.warning("Asistente de empleados: WhatsApp libre a Sergio falló: %s", res.get('error'))
        template = self.env['whatsapp.template'].sudo().search([
            ('template_name', '=', ALERT_TEMPLATE), ('status', '=', 'approved'),
            ('wa_account_id', '=', account.id)], limit=1)
        if not template:
            return "no salió: ventana cerrada y la plantilla cristal_aviso_interno no está aprobada"
        try:
            with self.env.cr.savepoint():
                composer = self.env['whatsapp.composer'].sudo().with_context(
                    active_model='res.partner', active_ids=[partner.id], from_cristal_agent=True,
                ).create({'res_model': 'res.partner', 'res_ids': str(partner.id),
                          'wa_template_id': template.id, 'phone': mobile,
                          'free_text_1': first, 'free_text_2': ' '.join(question.split())[:500]})
                composer.action_send_whatsapp_template()
        except Exception as e:
            _logger.exception("Asistente de empleados: plantilla a Sergio falló")
            return f"no salió: {e}"[:180]
        return "plantilla cristal_aviso_interno"

    # ───────────────────────── Respuesta de Sergio ─────────────────────────
    def relay(self, answer_html, source):
        """Le pasa al empleado lo que contestó Sergio, en el mismo registro."""
        config = self.env['cristal.agent.config'].sudo().get_active()
        bot = config.bot_partner_id or self.env.ref('base.partner_root')
        for escalation in self.filtered(lambda e: e.state == 'open'):
            record = escalation.record()
            text = html2plaintext(answer_html or '').strip()
            escalation.write({'state': 'answered', 'answer': text or source})
            if not record:
                continue
            first = (escalation.employee_partner_id.name or '').split(' ')[0]
            body = (Markup("<p>%s, Sergio contestó: %s</p>") % (first, text) if text
                    else Markup("<p>%s, Sergio marcó tu consulta como resuelta.</p>") % first)
            record.with_context(cristal_employee_bot=True, from_cristal_agent=True).message_post(
                body=body, message_type='comment', subtype_xmlid='mail.mt_note',
                author_id=bot.id, partner_ids=escalation.employee_partner_id.ids)
            if source == 'chatter' and escalation.activity_id:
                escalation.activity_id.with_context(cristal_employee_relayed=True).action_feedback(
                    feedback="Respondida en el chatter")
