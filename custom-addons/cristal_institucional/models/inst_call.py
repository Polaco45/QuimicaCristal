from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

from .res_partner import (
    ACCOUNT_OUTCOMES, CALL_CHANNELS, CALL_RESULTS, INST_FRECUENCIAS, INST_STAGES, OUTCOME_RULES)


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
    channel = fields.Selection(CALL_CHANNELS, 'Canal', default='llamada')
    result = fields.Selection(CALL_RESULTS, 'Resultado', required=True)
    outcome = fields.Selection(ACCOUNT_OUTCOMES, 'Qué dijo')
    notes = fields.Text('Qué pasó')
    stage = fields.Selection(INST_STAGES, 'Etapa en ese momento')
    is_contact = fields.Boolean('Hubo conversación', compute='_compute_is_contact', store=True)

    @api.depends('result')
    def _compute_is_contact(self):
        for call in self:
            call.is_contact = call.result not in ('no_atendio', 'whatsapp', 'omitido')


class CristalInstCallWizard(models.TransientModel):
    _name = 'cristal.inst.call.wizard'
    _description = 'Institucional: registrar contacto'

    partner_id = fields.Many2one('res.partner', 'Empresa', required=True)
    channel = fields.Selection(CALL_CHANNELS, 'Por dónde fue', required=True, default='llamada')
    is_account = fields.Boolean('Ya es cliente', compute='_compute_is_account')
    outcome = fields.Selection(
        ACCOUNT_OUTCOMES, 'Qué te dijo',
        help='De esto depende el próximo paso. Si no elegís nada, sigue la cadena normal.')
    outcome_hint = fields.Char('Qué va a pasar', compute='_compute_outcome_hint')
    script = fields.Html('Guion', related='partner_id.inst_script', sanitize=False)
    chain_message = fields.Text('Mensaje para mandar', related='partner_id.inst_chain_message')
    decisor_whatsapp = fields.Char('Mandar a', related='partner_id.inst_decisor_phone')
    result = fields.Selection([r for r in CALL_RESULTS if r[0] != 'omitido'], 'Resultado', required=True,
                              default='no_atendio')
    notes = fields.Text('Qué pasó')
    next_date = fields.Date(
        'Volver a contactar el',
        help='Dejalo vacío y el sistema pone la fecha que corresponde a la etapa.')
    # Quién decide
    decisor_name = fields.Char('Nombre de quien decide')
    decisor_phone = fields.Char('WhatsApp de quien decide')
    decisor_function = fields.Char('Puesto')
    # Otra persona de la empresa (sin reemplazar a quien decide)
    extra_name = fields.Char('Otro contacto')
    extra_phone = fields.Char('Su teléfono o WhatsApp')
    extra_function = fields.Char('Su puesto')
    people = fields.Char('Contactos cargados', related='partner_id.inst_people')
    # Ficha
    productos = fields.Text('Qué productos usan y cuánto')
    proveedor = fields.Char('A quién le compran hoy')
    frecuencia = fields.Selection(INST_FRECUENCIAS, 'Cada cuánto compran')
    street = fields.Char('Dirección de entrega')
    horario = fields.Char('Horario de entrega')
    discard_reason = fields.Char('Motivo')

    @api.depends('partner_id')
    def _compute_is_account(self):
        for wizard in self:
            wizard.is_account = wizard.partner_id.commercial_partner_id.inst_stage in (
                'recurrente', 'pedido_formal', 'inactivo')

    @api.depends('outcome', 'next_date')
    def _compute_outcome_hint(self):
        today = fields.Date.context_today(self)
        for wizard in self:
            rule = OUTCOME_RULES.get(wizard.outcome)
            if not rule:
                wizard.outcome_hint = False
                continue
            when = wizard.next_date or (today + timedelta(days=rule[1]))
            wizard.outcome_hint = 'Tu próximo paso: "%s", el %s.' % (rule[0], when.strftime('%d/%m/%Y'))

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
                'channel': partner.inst_chain_channel if partner.inst_chain_channel in (
                    'llamada', 'whatsapp', 'visita') else 'llamada',
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
        talked = self.result not in ('no_atendio', 'whatsapp')
        if talked and not partner.inst_contactado:
            vals['inst_contactado'] = today

        decisor = self._get_or_create_decisor(partner)
        extra = (self.extra_name or '').strip()
        if extra:
            Partner = self.env['res.partner']
            person = Partner.search([('parent_id', '=', partner.id), ('name', '=ilike', extra)], limit=1)
            pvals = {}
            if self.extra_phone:
                pvals['mobile'] = self.extra_phone.strip()
            if self.extra_function:
                pvals['function'] = self.extra_function.strip()
            if person:
                if pvals:
                    person.write(pvals)
            else:
                pvals.update({'name': extra, 'parent_id': partner.id, 'type': 'contact', 'is_company': False})
                Partner.create(pvals)
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

        if self.result == 'no_atendio':
            vals['inst_attempts'] = partner.inst_attempts + 1
            vals['inst_postponed_until'] = self.next_date or _next_workday(today)
        else:
            vals['inst_attempts'] = 0
            vals['inst_postponed_until'] = self.next_date or (
                (today + timedelta(days=3)) if self.result == 'whatsapp' else False)
        # El paso de la cadena queda hecho y se pasa al siguiente
        step_done = self.result in ('contacto', 'decisor', 'kit', 'posponer') or (
            self.result == 'whatsapp' and partner.inst_chain_step_id.channel == 'whatsapp')
        if partner.inst_chain_step_id and step_done:
            vals['inst_chain_done'] = partner.inst_chain_step_id.sequence
        if self.result == 'no_califica':
            vals['inst_discarded'] = True
            vals['inst_discard_reason'] = (
                self.discard_reason or (self.notes or '').strip().split('\n')[0][:120] or 'No califica')

        # Lo que contestó el cliente define el próximo paso (pisa la cadena automática)
        outcome = self.outcome if (talked and self.is_account) else False
        if self.result == 'pedido':
            vals['inst_custom_step'] = 'Cargar el pedido que hizo'
            vals['inst_custom_set'] = today
            vals['inst_postponed_until'] = False
        elif outcome and outcome in OUTCOME_RULES:
            text, days = OUTCOME_RULES[outcome]
            vals['inst_custom_step'] = text
            vals['inst_custom_set'] = today
            vals['inst_postponed_until'] = self.next_date or (today + timedelta(days=days))
        elif talked:
            vals['inst_custom_step'] = False
            vals['inst_custom_set'] = False

        self.env['cristal.inst.call'].create({
            'partner_id': partner.id,
            'channel': self.channel,
            'result': self.result,
            'outcome': outcome,
            'notes': self.notes,
            'stage': partner.inst_stage,
        })
        label = dict(CALL_RESULTS)[self.result]
        if outcome:
            label = '%s. %s' % (label, dict(ACCOUNT_OUTCOMES)[outcome])
        body = Markup('<p><strong>Contacto institucional por %s: %s</strong></p>') % (
            dict(CALL_CHANNELS)[self.channel].lower(), label)
        if self.notes:
            body += Markup('<p>%s</p>') % self.notes
        if self.next_date:
            body += Markup('<p>Volver a contactar el %s.</p>') % self.next_date.strftime('%d/%m/%Y')
        partner.message_post(body=body, subtype_xmlid='mail.mt_note')

        # Ya se trabajó hoy: sale de "Mi día" y vuelve a la fila con su nueva prioridad
        vals.update({'inst_queue_date': False, 'inst_today': False, 'inst_pinned_date': False})
        if self.result != 'no_atendio':
            vals['inst_missing_data'] = False
        partner.with_context(inst_engine=True).write(vals)
        if self.result == 'kit' and not partner.inst_kit_order_id:
            # Aceptó el kit: el pedido sin cargo se arma solo
            partner.action_inst_send_kit()
        self.env['cristal.inst.engine'].recompute(partner)
        return {'type': 'ir.actions.act_window_close'}


SKIP_REASONS = [
    ('otro_dia', 'Lo dejo para otro día'),
    ('hecho', 'Ya lo resolví por otro lado'),
    ('no_ahora', 'No hace falta contactarlo por ahora'),
    ('sin_dato', 'No tengo teléfono o el dato está mal'),
    ('no_contactar', 'No contactarlo más'),
    ('no_institucional', 'No es un cliente institucional'),
]


class CristalInstSkipWizard(models.TransientModel):
    _name = 'cristal.inst.skip.wizard'
    _description = 'Institucional: sacar una cuenta del día'

    partner_id = fields.Many2one('res.partner', 'Empresa', required=True)
    reason = fields.Selection(SKIP_REASONS, 'Por qué la sacás', required=True, default='otro_dia')
    date = fields.Date('Volver a traerla el', default=lambda self: _next_workday(fields.Date.context_today(self)))
    notes = fields.Char('Comentario')
    consequence = fields.Char('Qué va a pasar', compute='_compute_consequence')

    @api.depends('reason', 'date')
    def _compute_consequence(self):
        for wizard in self:
            when = wizard.date.strftime('%d/%m/%Y') if wizard.date else 'la fecha que elijas'
            wizard.consequence = {
                'otro_dia': 'Vuelve a tu lista el %s, con el mismo paso.' % when,
                'hecho': 'Se da por hecho el paso de hoy y pasa al siguiente de su cadena.',
                'no_ahora': 'No te aparece por 30 días. Si compra antes, se acomoda sola.',
                'sin_dato': 'Queda marcada como "falta un teléfono o contacto válido" y vuelve en 7 días '
                            'para conseguirlo.',
                'no_contactar': 'Pasa a Descartado: no se le agenda ningún paso ni recibe avisos.',
                'no_institucional': 'Sale del flujo institucional y el sistema no la vuelve a sumar.',
            }.get(wizard.reason, False)

    def action_confirm(self):
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        today = fields.Date.context_today(self)
        label = dict(SKIP_REASONS)[self.reason]
        note = label + ((': %s' % self.notes) if self.notes else '')
        if self.reason == 'no_institucional':
            partner.message_post(
                body=Markup('<p><strong>Sacada del flujo institucional</strong></p><p>%s</p>') % note,
                subtype_xmlid='mail.mt_note')
            partner.write({'inst_excluded': True})
            return {'type': 'ir.actions.act_window_close'}
        vals = {'inst_today': False, 'inst_pinned_date': False, 'inst_queue_date': False,
                'inst_skip_date': today}
        if self.reason == 'otro_dia':
            if not self.date or self.date <= today:
                raise UserError('Elegí una fecha posterior a hoy para volver a traerla.')
            vals['inst_postponed_until'] = self.date
        elif self.reason == 'hecho':
            vals['inst_attempts'] = 0
            vals['inst_last_call'] = today
            if partner.inst_chain_step_id:
                vals['inst_chain_done'] = partner.inst_chain_step_id.sequence
            else:
                vals['inst_postponed_until'] = today + timedelta(days=7)
        elif self.reason == 'no_ahora':
            vals['inst_postponed_until'] = today + timedelta(days=30)
        elif self.reason == 'sin_dato':
            vals['inst_missing_data'] = True
            vals['inst_postponed_until'] = today + timedelta(days=7)
        elif self.reason == 'no_contactar':
            vals['inst_discarded'] = True
            vals['inst_discard_reason'] = self.notes or 'No contactar más'
        self.env['cristal.inst.call'].create({
            'partner_id': partner.id, 'result': 'omitido', 'notes': note, 'stage': partner.inst_stage,
        })
        partner.message_post(
            body=Markup('<p><strong>Sacada de la lista del día</strong></p><p>%s</p>') % note,
            subtype_xmlid='mail.mt_note')
        partner.with_context(inst_engine=True).write(vals)
        self.env['cristal.inst.engine'].recompute(partner)
        return {'type': 'ir.actions.act_window_close'}
