# -*- coding: utf-8 -*-
"""
Visita de ruta — el registro de trabajo y control de cada visita.

Reemplaza a las actividades nativas como fuente de verdad: guarda estado,
resultado, notas, posposiciones e historial, para que Alejandra opere su día
(Kanban dinámico) y Joaco tenga el reporte de control vinculado al CRM.
"""
from odoo import api, fields, models

from .res_partner import RUTEO_VISIT_TYPES

VISIT_STATES = [
    ('pendiente', 'Por visitar'),
    ('visitada', 'Visitada'),
    ('pospuesta', 'Pospuesta'),
    ('no_visitada', 'No estaba'),
    ('cancelada', 'Sacada de la ruta'),
]

VISIT_OUTCOMES = [
    ('compro', 'Compró / hizo pedido'),
    ('cotizo', 'Pidió cotización'),
    ('interesado', 'Interesado, seguir'),
    ('dejo_muestra', 'Dejó muestra'),
    ('no_compro', 'No compró'),
    ('no_estaba', 'No estaba / cerrado'),
    ('otro', 'Otro'),
]


class CristalRutaVisita(models.Model):
    _name = 'cristal.ruta.visita'
    _description = 'Visita de ruta'
    _inherit = ['mail.thread']
    _order = 'visit_date desc, sequence, id'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one(
        'res.partner', string="Cliente", required=True, ondelete='cascade',
        index=True, tracking=True)
    user_id = fields.Many2one(
        'res.users', string="Vendedor", index=True, tracking=True,
        default=lambda self: self.env.user)
    zona_id = fields.Many2one('cristal.ruta.zona', string="Zona", index=True)
    lead_id = fields.Many2one(
        'crm.lead', string="Oportunidad",
        help="Oportunidad del CRM vinculada a esta visita.")
    visit_date = fields.Date(
        string="Fecha", required=True, index=True, tracking=True,
        default=fields.Date.context_today)
    sequence = fields.Integer(string="Orden", default=10)

    visit_type = fields.Selection(RUTEO_VISIT_TYPES, string="Tipo de visita")
    priority_score = fields.Integer(string="Prioridad")
    reason = fields.Char(string="Motivo")

    state = fields.Selection(
        VISIT_STATES, string="Estado", default='pendiente', required=True,
        index=True, tracking=True)
    origin = fields.Selection(
        [('auto', 'Automática'), ('manual', 'Agregada a mano')],
        string="Origen", default='auto', tracking=True,
        help="Automática = la armó el sistema; Manual = la agregó la vendedora.")
    outcome = fields.Selection(VISIT_OUTCOMES, string="Resultado", tracking=True)
    notes = fields.Text(string="Detalle / notas")
    postponed_to = fields.Date(string="Pospuesta para")
    visited_at = fields.Datetime(string="Visitada el", readonly=True)

    # Datos del cliente (relacionados, para vistas y mapa)
    partner_latitude = fields.Float(related='partner_id.partner_latitude', string="Latitud")
    partner_longitude = fields.Float(related='partner_id.partner_longitude', string="Longitud")
    partner_city = fields.Char(related='partner_id.city', string="Ciudad")
    partner_street = fields.Char(related='partner_id.street', string="Dirección")
    partner_is_located = fields.Boolean(related='partner_id.ruteo_is_located', string="Ubicado")
    color = fields.Integer(related='partner_id.ruteo_pin_color', string="Color")

    # ─────────── Acciones de la vendedora ───────────
    def action_navigate(self):
        """Abre Google Maps hacia el cliente."""
        self.ensure_one()
        return self.partner_id.action_ruteo_open_maps()

    def action_visitada(self):
        self.write({'state': 'visitada'})
        return True

    def action_no_visitada(self):
        self.write({'state': 'no_visitada'})
        return True

    def action_cancelar(self):
        self.write({'state': 'cancelada'})
        return True

    def action_posponer(self):
        """Abre el asistente para reprogramar la visita a otra fecha."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': "Posponer visita",
            'res_model': 'cristal.ruta.visita.postpone',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_visita_id': self.id},
        }

    def action_open_lead(self):
        self.ensure_one()
        if not self.lead_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': "Oportunidad",
            'res_model': 'crm.lead',
            'res_id': self.lead_id.id,
            'view_mode': 'form',
        }

    # ─────────── Efectos de cambiar de estado ───────────
    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') == 'visitada':
            for visita in self:
                if not visita.visited_at:
                    super(CristalRutaVisita, visita).write(
                        {'visited_at': fields.Datetime.now()})
                # Registra la visita en el cliente → recalcula próxima visita.
                visita.partner_id._ruteo_register_visit(visita.visit_date)
                visita._post_to_crm()
        return res

    def _post_to_crm(self):
        """Deja registro de la visita en la oportunidad (o en el cliente)."""
        for visita in self:
            outcome_label = dict(VISIT_OUTCOMES).get(visita.outcome or '', '—')
            body = "<b>Visita realizada</b> (%s) — resultado: %s" % (
                fields.Date.to_string(visita.visit_date), outcome_label)
            if visita.notes:
                body += "<br/>%s" % visita.notes
            target = visita.lead_id or visita.partner_id
            target.message_post(body=body)

    # ─────────── Reporte diario a la gerencia ───────────
    @api.model
    def _cron_ruteo_daily_report(self, target_date=None):
        """Envía por email a los gerentes de venta el resumen del día: qué pasó
        con cada cliente de cada vendedor (visitadas, pospuestas, agregadas a
        mano, con resultado y notas)."""
        target = target_date or fields.Date.context_today(self)
        visitas = self.search([('visit_date', '=', target)])
        if not visitas:
            return
        managers = self.env.ref('sales_team.group_sale_manager').users
        recipients = [e for e in managers.mapped('email') if e]
        if not recipients:
            return
        self.env['mail.mail'].sudo().create({
            'subject': "Ruteo — resumen del %s" % fields.Date.to_string(target),
            'body_html': self._build_daily_report_html(target, visitas),
            'email_to': ",".join(recipients),
            'auto_delete': True,
        }).send()

    @api.model
    def _build_daily_report_html(self, target, visitas):
        states = dict(VISIT_STATES)
        outcomes = dict(VISIT_OUTCOMES)
        blocks = ["<h2>Ruteo — %s</h2>" % fields.Date.to_string(target)]
        for user in visitas.mapped('user_id'):
            uv = visitas.filtered(lambda v: v.user_id == user)
            done = len(uv.filtered(lambda v: v.state == 'visitada'))
            manual = len(uv.filtered(lambda v: v.origin == 'manual'))
            blocks.append(
                "<h3>%s — %s de %s visitadas%s</h3>" % (
                    user.name, done, len(uv),
                    (" · %s agregadas a mano" % manual) if manual else ""))
            blocks.append("<table border='1' cellpadding='5' "
                          "style='border-collapse:collapse;font-size:13px'>")
            blocks.append("<tr style='background:#f0f0f0'><th>#</th><th>Cliente</th>"
                          "<th>Estado</th><th>Resultado</th><th>Notas</th><th>Origen</th></tr>")
            for v in uv.sorted(key=lambda r: r.sequence):
                blocks.append(
                    "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                        v.sequence, v.partner_id.display_name, states.get(v.state, ''),
                        outcomes.get(v.outcome or '', ''),
                        (v.notes or '').replace('\n', ' '),
                        'Manual' if v.origin == 'manual' else 'Auto'))
            blocks.append("</table><br/>")
        return "".join(blocks)
