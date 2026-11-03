# -*- coding: utf-8 -*-
"""Pedido mensual de listas de precios: el agente arma la tanda y Sergio la aprueba."""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

ACTIVE_DAYS = 365   # proveedores con alguna compra en el último año


class CristalComprasListRequest(models.Model):
    _name = 'cristal.compras.list.request'
    _description = "Cristal — pedido mensual de listas de precios"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string="Pedido", required=True)
    date = fields.Date(string="Fecha", default=fields.Date.context_today, required=True)
    state = fields.Selection([('draft', "Para aprobar"), ('sent', "Enviado"), ('cancel', "Descartado")],
                             string="Estado", default='draft', required=True, tracking=True)
    line_ids = fields.One2many('cristal.compras.list.request.line', 'request_id', string="Proveedores")

    @api.model
    def _first_monday(self, day):
        first = day.replace(day=1)
        return first + timedelta(days=(7 - first.weekday()) % 7)

    @api.model
    def _cron_prepare(self):
        """Corre todos los días; el primer lunes del mes arma la tanda (una sola por mes)."""
        today = fields.Date.context_today(self)
        if today != self._first_monday(today):
            return False
        return self.prepare(today)

    @api.model
    def prepare(self, day=None):
        day = day or fields.Date.context_today(self)
        month_start = day.replace(day=1)
        if self.search_count([('date', '>=', month_start), ('date', '<', month_start + relativedelta(months=1)),
                              ('state', '!=', 'cancel')]):
            return False
        since = fields.Datetime.now() - timedelta(days=ACTIVE_DAYS)
        orders = self.env['purchase.order'].sudo().search([('state', 'in', ['purchase', 'done']),
                                                           ('date_order', '>=', since)])
        suppliers = orders.mapped('partner_id.commercial_partner_id').filtered(
            lambda p: not p.cristal_price_list_exempt
            and not (p.cristal_price_list_date and p.cristal_price_list_date >= month_start))
        if not suppliers:
            return False
        request = self.create({
            'name': _("Listas de %s", day.strftime('%m/%Y')),
            'date': day,
            'line_ids': [(0, 0, {'partner_id': p.id, 'mode': p.cristal_price_list_mode or 'list'})
                         for p in suppliers.sorted('name')],
        })
        user = self.env['cristal.compras']._notify_user()
        if user:
            request.activity_schedule(
                'mail.mail_activity_data_todo', user_id=user.id,
                summary=_("Aprobar el pedido de listas del mes (%s proveedores)", len(suppliers)),
                note=_("Destildá a quien no haga falta y apretá «Enviar». Nada sale sin tu OK."))
        return request

    def action_send(self):
        Compras = self.env['cristal.compras']
        Compras._check_ok()
        for request in self:
            if request.state != 'draft':
                raise UserError(_("Este pedido ya se envió o se descartó."))
            for line in request.line_ids.filtered('include'):
                ok, detail = Compras.send(line.partner_id, line.partner_id, line.mode)
                line.write({'result': detail, 'sent': ok})
            request.state = 'sent'
            request.activity_ids.action_feedback(feedback=_("Enviado"))
        return True

    def action_cancel(self):
        self.write({'state': 'cancel'})
        self.activity_ids.unlink()


class CristalComprasListRequestLine(models.Model):
    _name = 'cristal.compras.list.request.line'
    _description = "Cristal — proveedor del pedido mensual de listas"
    _order = 'partner_id'

    request_id = fields.Many2one('cristal.compras.list.request', required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string="Proveedor", required=True)
    mode = fields.Selection([('list', "Lista completa"), ('raw', "Materias primas para cotizar")],
                            string="Qué se pide", default='list', required=True)
    include = fields.Boolean(string="Mandar", default=True)
    channel = fields.Char(string="Canal", compute='_compute_channel')
    sent = fields.Boolean(string="Salió", readonly=True)
    result = fields.Char(string="Resultado", readonly=True)

    def _compute_channel(self):
        Compras = self.env['cristal.compras']
        for line in self:
            line.channel = dict(line.partner_id._fields['cristal_buy_channel'].selection).get(
                Compras._channel(line.partner_id))
