# -*- coding: utf-8 -*-
from datetime import date
from calendar import monthrange

from odoo import api, fields, models, _
from odoo.exceptions import UserError


MESES_OPTIONS = [
    ('1', 'Enero'), ('2', 'Febrero'), ('3', 'Marzo'), ('4', 'Abril'),
    ('5', 'Mayo'), ('6', 'Junio'), ('7', 'Julio'), ('8', 'Agosto'),
    ('9', 'Septiembre'), ('10', 'Octubre'), ('11', 'Noviembre'), ('12', 'Diciembre'),
]


class QuimicaCristalReporteDescargaWizard(models.TransientModel):
    _name = 'quimica.cristal.reporte.descarga.wizard'
    _description = 'Generar reporte mensual manualmente'

    partner_id = fields.Many2one(
        'res.partner', string='Cliente', required=True,
        domain=[('parent_id', '=', False), ('customer_rank', '>', 0)],
        help='Cliente para el que querés generar el reporte mensual',
    )

    period_year = fields.Integer(
        string='Año', required=True,
        default=lambda self: self._default_year(),
    )
    period_month = fields.Selection(
        MESES_OPTIONS, string='Mes', required=True,
        default=lambda self: self._default_month(),
    )

    accion = fields.Selection([
        ('preview', 'Solo descargar PDF'),
        ('send', 'Generar y enviar por email'),
    ], string='Acción', default='preview', required=True)

    info_partner = fields.Html(
        compute='_compute_info_partner', readonly=True,
    )

    def _default_year(self):
        """Año del mes anterior al actual."""
        today = date.today()
        if today.month == 1:
            return today.year - 1
        return today.year

    def _default_month(self):
        """Mes anterior al actual."""
        today = date.today()
        if today.month == 1:
            return '12'
        return str(today.month - 1)

    @api.depends('partner_id', 'period_year', 'period_month')
    def _compute_info_partner(self):
        """Muestra info útil del partner antes de generar."""
        for rec in self:
            if not rec.partner_id or not rec.period_year or not rec.period_month:
                rec.info_partner = ''
                continue
            month = int(rec.period_month)
            last_day = monthrange(rec.period_year, month)[1]
            df = date(rec.period_year, month, 1)
            dt = date(rec.period_year, month, last_day)

            # Contar facturas en el período
            invs = rec.env['account.move'].search_count([
                ('commercial_partner_id', '=', rec.partner_id.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', df),
                ('invoice_date', '<=', dt),
                ('company_id', '=', rec.env.company.id),
            ])
            ncs = rec.env['account.move'].search_count([
                ('commercial_partner_id', '=', rec.partner_id.id),
                ('move_type', '=', 'out_refund'),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', df),
                ('invoice_date', '<=', dt),
                ('company_id', '=', rec.env.company.id),
            ])

            # ¿Tiene tag Plan Control?
            tag = rec.env['res.partner.category'].search([
                ('name', '=', 'Plan Control'),
            ], limit=1)
            tiene_tag = tag and tag.id in rec.partner_id.category_id.ids

            email = rec.partner_id.email or ''
            if not email:
                contact = rec.env['res.partner'].search([
                    ('parent_id', '=', rec.partner_id.id),
                    ('email', '!=', False),
                ], limit=1)
                email = contact.email if contact else 'sin email'

            warn = ''
            if not tiene_tag:
                warn += (
                    '<div style="color:#d86b0f;font-weight:600;margin-bottom:6px">'
                    '⚠ Este cliente NO tiene la etiqueta "Plan Control". '
                    'Podés generar el reporte de todas formas.</div>'
                )
            if invs == 0:
                warn += (
                    '<div style="color:#d86b0f;font-weight:600;margin-bottom:6px">'
                    '⚠ Este cliente NO tiene facturas en el período seleccionado.</div>'
                )

            rec.info_partner = f'''
                {warn}
                <table style="border-collapse:collapse;font-size:13px">
                  <tr><td style="padding:3px 8px;color:#666"><b>Email destino:</b></td><td>{email}</td></tr>
                  <tr><td style="padding:3px 8px;color:#666"><b>Facturas en el período:</b></td><td>{invs}</td></tr>
                  <tr><td style="padding:3px 8px;color:#666"><b>Notas de crédito:</b></td><td>{ncs}</td></tr>
                  <tr><td style="padding:3px 8px;color:#666"><b>Plan Control:</b></td><td>{'Sí' if tiene_tag else 'No'}</td></tr>
                </table>
            '''

    def action_execute(self):
        """Ejecuta la acción seleccionada."""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Seleccioná un cliente'))

        Reporte = self.env['quimica.cristal.reporte.mensual']

        # ¿Ya existe el reporte de este período?
        existing = Reporte.search([
            ('partner_id', '=', self.partner_id.id),
            ('period_year', '=', self.period_year),
            ('period_month', '=', int(self.period_month)),
        ], limit=1)

        if existing:
            # Re-generar (overwrite)
            reporte = existing
            reporte._do_generate()
        else:
            reporte = Reporte.create({
                'partner_id': self.partner_id.id,
                'period_year': self.period_year,
                'period_month': int(self.period_month),
            })
            reporte._do_generate()

        if self.accion == 'send':
            reporte._do_send_email()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Reporte enviado'),
                    'message': _('Se envió el reporte de %s a %s') % (
                        reporte.display_name, reporte.sent_email,
                    ),
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window',
                        'res_model': 'quimica.cristal.reporte.mensual',
                        'res_id': reporte.id,
                        'view_mode': 'form',
                        'target': 'current',
                    },
                },
            }
        else:
            # Descargar PDF
            return self.env.ref(
                'quimica_cristal_reporte_mensual.action_report_reporte_mensual'
            ).report_action(reporte)
