from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

from .res_partner import CALL_RESULTS, INST_FRECUENCIAS, INST_STAGES


def _next_workday(day):
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


class CristalInstCall(models.Model):
    _name = 'cristal.inst.call'
    _description = 'Institucional: contacto registrado'
    _order = 'date desc, id desc'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one('res.partner', 'Empresa', required=True, index=True, ondelete='cascade')
    date = fields.Datetime('Fecha', required=True, default=fields.Datetime.now, index=True)
    user_id = fields.Many2one('res.users', 'Quién llamó', default=lambda self: self.env.user)
    result = fields.Selection(CALL_RESULTS, 'Resultado', required=True)
    notes = fields.Text('Qué pasó')
    stage = fields.Selection(INST_STAGES, 'Etapa en ese momento')
    is_contact = fields.Boolean('Hubo conversación', compute='_compute_is_contact', store=True)

    @api.depends('result')
    def _compute_is_contact(self):
        for call in self:
            call.is_contact = call.result != 'no_atendio'


class CristalInstCallWizard(models.TransientModel):
    _name = 'cristal.inst.call.wizard'
    _description = 'Institucional: registrar llamada'

    partner_id = fields.Many2one('res.partner', 'Empresa', required=True)
    script = fields.Html('Guion', related='partner_id.inst_script', sanitize=False)
    result = fields.Selection(CALL_RESULTS, 'Resultado', required=True, default='no_atendio')
    notes = fields.Text('Qué pasó')
    next_date = fields.Date(
        'Volver a contactar el',
        help='Dejalo vacío y el sistema pone la fecha que corresponde a la etapa.')
    # Quién decide
    decisor_name = fields.Char('Nombre de quien decide')
    decisor_phone = fields.Char('WhatsApp de quien decide')
    decisor_function = fields.Char('Puesto')
    # Ficha
    productos = fields.Text('Qué productos usan y cuánto')
    proveedor = fields.Char('A quién le compran hoy')
    frecuencia = fields.Selection(INST_FRECUENCIAS, 'Cada cuánto compran')
    street = fields.Char('Dirección de entrega')
    horario = fields.Char('Horario de entrega')
    discard_reason = fields.Char('Motivo')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        partner = self.env['res.partner'].browse(
            res.get('partner_id') or self.env.context.get('default_partner_id')
            or self.env.context.get('active_id'))
        if partner:
            partner = partner.commercial_partner_id
            decisor = partner.inst_decisor_id
            res.update({
                'partner_id': partner.id,
                'decisor_name': decisor.name or False,
                'decisor_phone': decisor.mobile or decisor.phone or False,
                'decisor_function': decisor.function or False,
                'productos': partner.inst_productos or False,
                'proveedor': partner.inst_proveedor or False,
                'frecuencia': partner.inst_frecuencia or False,
                'street': partner.street or False,
                'horario': partner.inst_entrega_horario or False,
            })
        return res

    def _get_or_create_decisor(self, partner):
        name = (self.decisor_name or '').strip()
        if not name:
            return self.env['res.partner']
        Partner = self.env['res.partner']
        decisor = Partner.search([('parent_id', '=', partner.id), ('name', '=ilike', name)], limit=1)
        vals = {}
        if self.decisor_phone:
            vals['mobile'] = self.decisor_phone.strip()
        if self.decisor_function:
            vals['function'] = self.decisor_function.strip()
        if decisor:
            if vals:
                decisor.write(vals)
        else:
            vals.update({'name': name, 'parent_id': partner.id, 'type': 'contact', 'is_company': False})
            decisor = Partner.create(vals)
        return decisor

    def action_confirm(self):
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        if not partner.inst_is:
            raise UserError('Esta empresa no está marcada como cliente institucional.')
        today = fields.Date.context_today(self)
        vals = {'inst_last_call': today, 'inst_last_result': self.result}
        talked = self.result != 'no_atendio'
        if talked and not partner.inst_contactado:
            vals['inst_contactado'] = today

        decisor = self._get_or_create_decisor(partner)
        if decisor and decisor != partner.inst_decisor_id:
            vals['inst_decisor_id'] = decisor.id
        ficha = {
            'inst_productos': self.productos,
            'inst_proveedor': self.proveedor,
            'inst_frecuencia': self.frecuencia,
            'street': self.street,
            'inst_entrega_horario': self.horario,
        }
        for field_name, value in ficha.items():
            value = value.strip() if isinstance(value, str) else value
            if value and value != partner[field_name]:
                vals[field_name] = value

        if talked:
            vals['inst_attempts'] = 0
            vals['inst_postponed_until'] = self.next_date or False
        else:
            vals['inst_attempts'] = partner.inst_attempts + 1
            vals['inst_postponed_until'] = self.next_date or _next_workday(today)
        if self.result == 'no_califica':
            vals['inst_discarded'] = True
            vals['inst_discard_reason'] = (
                self.discard_reason or (self.notes or '').strip().split('\n')[0][:120] or 'No califica')

        self.env['cristal.inst.call'].create({
            'partner_id': partner.id,
            'result': self.result,
            'notes': self.notes,
            'stage': partner.inst_stage,
        })
        label = dict(CALL_RESULTS)[self.result]
        body = Markup('<p><strong>Llamada institucional: %s</strong></p>') % label
        if self.notes:
            body += Markup('<p>%s</p>') % self.notes
        if self.next_date:
            body += Markup('<p>Volver a contactar el %s.</p>') % self.next_date.strftime('%d/%m/%Y')
        partner.message_post(body=body, subtype_xmlid='mail.mt_note')

        partner.with_context(inst_engine=True).write(vals)
        self.env['cristal.inst.engine'].recompute(partner)
        return {'type': 'ir.actions.act_window_close'}
