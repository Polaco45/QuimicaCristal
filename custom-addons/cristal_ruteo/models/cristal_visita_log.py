# -*- coding: utf-8 -*-
"""
Registro de visitas (control gerencial).

Cada visita registrada ("Visité hoy") y cada posposición deja acá un asiento
permanente: qué pasó, con qué cliente, quién y cuándo. Solo lo ve el grupo de
control. Un cron a las 8am envía el reporte del día anterior.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

from .res_partner import RUTEO_VISIT_TYPES
from .res_partner_visitas import VISIT_OUTCOMES

_logger = logging.getLogger(__name__)


class CristalVisitaLog(models.Model):
    _name = 'cristal.visita.log'
    _description = 'Registro de visita'
    _order = 'visit_date desc, id desc'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one(
        'res.partner', string="Cliente", required=True, index=True, ondelete='cascade')
    partner_city = fields.Char(related='partner_id.city', string="Ciudad", store=True)
    visit_date = fields.Date(
        string="Fecha", required=True, index=True, default=fields.Date.context_today)
    user_id = fields.Many2one('res.users', string="Vendedor", index=True)
    action_type = fields.Selection([
        ('visita', 'Visita realizada'),
        ('posposicion', 'Pospuesta'),
    ], string="Acción", default='visita', required=True, index=True)
    visit_type = fields.Selection(RUTEO_VISIT_TYPES, string="Tipo de visita")
    outcome = fields.Selection(VISIT_OUTCOMES, string="Resultado", index=True)
    note = fields.Text(string="Detalle")
    lead_id = fields.Many2one('crm.lead', string="Oportunidad")
    genero_pedido = fields.Boolean(
        string="Generó pedido", compute='_compute_genero_pedido',
        help="Si la familia del cliente hizo un pedido dentro de los 7 días "
             "posteriores a la visita (mide la conversión).")

    def _compute_genero_pedido(self):
        SaleOrder = self.env['sale.order'].sudo()
        for log in self:
            if not log.visit_date:
                log.genero_pedido = False
                continue
            commercial = log.partner_id.commercial_partner_id or log.partner_id
            desde = fields.Datetime.to_datetime(log.visit_date)
            hasta = desde + timedelta(days=8)
            log.genero_pedido = bool(SaleOrder.search_count([
                ('commercial_partner_id', '=', commercial.id),
                ('state', 'in', ['sale', 'done']),
                ('date_order', '>=', desde),
                ('date_order', '<', hasta),
            ]))

    # ─────────── Reporte diario (8am) ───────────
    @api.model
    def _cron_daily_report(self, target_date=None):
        """Envía a la gerencia (grupo de control) el resumen del día anterior."""
        if not target_date:
            target_date = fields.Date.context_today(self) - timedelta(days=1)
        logs = self.search([('visit_date', '=', target_date)])
        group = self.env.ref('cristal_ruteo.group_visitas_control', raise_if_not_found=False)
        recipients = [e for e in (group.users.mapped('email') if group else []) if e]
        if not recipients:
            return
        # Se manda igual aunque no haya visitas: así se distingue "no hubo visitas"
        # de "el reporte dejó de funcionar".
        if logs:
            body = self._build_report_html(target_date, logs)
        else:
            body = ("<h2>Visitas — %s</h2><p>No se registró ninguna visita este día.</p>"
                    % fields.Date.to_string(target_date))
        self.env['mail.mail'].sudo().create({
            'subject': "Visitas — resumen del %s%s" % (
                fields.Date.to_string(target_date), "" if logs else " (sin visitas)"),
            'body_html': body,
            'email_to': ",".join(recipients),
            'auto_delete': True,
        }).send()

    @api.model
    def _build_report_html(self, target_date, logs):
        types = dict(RUTEO_VISIT_TYPES)
        actions = dict(self._fields['action_type'].selection)
        blocks = ["<h2>Visitas — %s</h2>" % fields.Date.to_string(target_date)]
        for user in logs.mapped('user_id') or [self.env['res.users']]:
            ulogs = logs.filtered(lambda l: l.user_id == user)
            if not ulogs:
                continue
            hechas = len(ulogs.filtered(lambda l: l.action_type == 'visita'))
            pospuestas = len(ulogs.filtered(lambda l: l.action_type == 'posposicion'))
            blocks.append("<h3>%s — %s visita(s), %s pospuesta(s)</h3>" % (
                user.name or 'Sin vendedor', hechas, pospuestas))
            blocks.append("<table border='1' cellpadding='5' "
                          "style='border-collapse:collapse;font-size:13px'>")
            blocks.append("<tr style='background:#f0f0f0'><th>Cliente</th><th>Acción</th>"
                          "<th>Tipo</th><th>Detalle</th></tr>")
            for log in ulogs:
                blocks.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    log.partner_id.display_name, actions.get(log.action_type, ''),
                    types.get(log.visit_type or '', ''),
                    (log.note or '').replace('\n', ' ')))
            blocks.append("</table><br/>")
        return "".join(blocks)
