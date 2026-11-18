from odoo import api, fields, models
from odoo.exceptions import UserError


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # Una sola tarjeta por empresa: es "la cuenta" dentro del CRM.
    inst_account = fields.Boolean(
        'Cuenta institucional', index=True, copy=False,
        help='Tarjeta única de la empresa en el flujo institucional. La mueve el sistema según los hechos.')
    inst_partner_id = fields.Many2one(
        'res.partner', 'Empresa', compute='_compute_inst_partner_id', store=True, index=True)

    # Lo que calcula el motor (se guarda en la empresa y se ve acá)
    inst_stage = fields.Selection(related='inst_partner_id.inst_stage', store=True, string='Etapa institucional')
    inst_alert = fields.Selection(related='inst_partner_id.inst_alert', store=True, string='Alerta')
    inst_reason = fields.Char(related='inst_partner_id.inst_reason', string='Por qué está en esta etapa')
    inst_next_step = fields.Char(related='inst_partner_id.inst_next_step', string='Próximo paso')
    inst_next_step_date = fields.Date(
        related='inst_partner_id.inst_next_step_date', store=True, string='Fecha del próximo paso')
    inst_deadline = fields.Date(related='inst_partner_id.inst_deadline', string='Fecha límite')
    inst_priority = fields.Float(related='inst_partner_id.inst_priority', store=True, string='Prioridad')
    inst_today = fields.Boolean(related='inst_partner_id.inst_today', store=True, string='Es para hoy')
    inst_auto_step_id = fields.Many2one(
        related='inst_partner_id.inst_auto_step_id', store=True, string='WhatsApp listo para salir solo')
    inst_chain_channel = fields.Selection(
        related='inst_partner_id.inst_chain_channel', store=True, string='Canal del próximo paso')
    inst_chain_message = fields.Text(related='inst_partner_id.inst_chain_message', string='Mensaje para mandar')
    inst_script = fields.Html(related='inst_partner_id.inst_script', string='Guion para la llamada', sanitize=False)
    inst_source = fields.Selection(related='inst_partner_id.inst_source', store=True, string='Cómo entró')
    inst_review = fields.Boolean(related='inst_partner_id.inst_review', store=True, readonly=False,
                                 string='Para revisar')

    # Ficha de la cuenta (se edita desde la oportunidad y queda en la empresa)
    inst_decisor_id = fields.Many2one(
        related='inst_partner_id.inst_decisor_id', readonly=False, string='Quién decide las compras')
    inst_decisor_phone = fields.Char(related='inst_partner_id.inst_decisor_phone', string='WhatsApp de quien decide')
    inst_productos = fields.Text(related='inst_partner_id.inst_productos', readonly=False,
                                 string='Qué productos usan y cuánto')
    inst_proveedor = fields.Char(related='inst_partner_id.inst_proveedor', readonly=False,
                                 string='A quién le compran hoy')
    inst_frecuencia = fields.Selection(related='inst_partner_id.inst_frecuencia', readonly=False,
                                       string='Cada cuánto compran')
    inst_entrega_horario = fields.Char(related='inst_partner_id.inst_entrega_horario', readonly=False,
                                       string='Horario de entrega')
    inst_ficha_pct = fields.Integer(related='inst_partner_id.inst_ficha_pct', string='Ficha completa (%)')
    inst_ficha_falta = fields.Char(related='inst_partner_id.inst_ficha_falta', string='Falta en la ficha')
    inst_postponed_until = fields.Date(related='inst_partner_id.inst_postponed_until', readonly=False,
                                       string='Pospuesto hasta')
    inst_kit_order_id = fields.Many2one(related='inst_partner_id.inst_kit_order_id', string='Pedido del kit')
    inst_kit_date = fields.Date(related='inst_partner_id.inst_kit_date', readonly=False, string='Kit entregado el')

    # Indicadores
    inst_order_count = fields.Integer(related='inst_partner_id.inst_order_count', string='Compras')
    inst_last_order = fields.Date(related='inst_partner_id.inst_last_order', store=True, string='Última compra')
    inst_cycle_days = fields.Integer(related='inst_partner_id.inst_cycle_days', string='Compra cada (días)')
    inst_next_expected = fields.Date(related='inst_partner_id.inst_next_expected', string='Próxima compra esperada')
    inst_days_late = fields.Integer(related='inst_partner_id.inst_days_late', string='Días de atraso')
    inst_margin_month = fields.Monetary(
        related='inst_partner_id.inst_margin_month', store=True, string='Margen por mes',
        currency_field='company_currency')
    inst_margin_12m = fields.Monetary(
        related='inst_partner_id.inst_margin_12m', string='Margen 12 meses', currency_field='company_currency')
    inst_amount_12m = fields.Monetary(
        related='inst_partner_id.inst_amount_12m', string='Venta 12 meses (sin IVA)',
        currency_field='company_currency')
    inst_margin_pct = fields.Float(related='inst_partner_id.inst_margin_pct', string='% de margen')
    inst_buys = fields.Char(related='inst_partner_id.inst_buys', string='Qué nos compra')
    inst_gaps = fields.Char(related='inst_partner_id.inst_gaps', string='Qué le falta sumar')
    inst_call_ids = fields.One2many(related='inst_partner_id.inst_call_ids', string='Contactos registrados')

    @api.depends('partner_id', 'partner_id.commercial_partner_id')
    def _compute_inst_partner_id(self):
        for lead in self:
            lead.inst_partner_id = lead.partner_id.commercial_partner_id or lead.partner_id

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        """El flujo institucional muestra solo sus columnas; el resto del CRM no las ve."""
        Engine = self.env['cristal.inst.engine']
        team = Engine._inst_team(create=False)
        if team and self._context.get('default_team_id') == team.id:
            return stages.sudo().search([('team_id', '=', team.id)], order='sequence, id')
        return super()._read_group_stage_ids(stages, domain)

    def _inst_partner(self):
        self.ensure_one()
        partner = self.inst_partner_id
        if not partner:
            raise UserError('Esta oportunidad no tiene una empresa asociada.')
        return partner

    def action_inst_call(self):
        return self._inst_partner().action_inst_call()

    def action_inst_send_kit(self):
        return self._inst_partner().action_inst_send_kit()

    def action_inst_first_offer(self):
        return self._inst_partner().action_inst_first_offer()

    def action_inst_orders(self):
        return self._inst_partner().action_inst_orders()

    def action_inst_add_today(self):
        """Agregar esta cuenta a "Mi día" de hoy, aunque el sistema la tuviera para otra fecha."""
        today = fields.Date.context_today(self)
        partners = self.mapped('inst_partner_id').sudo().filtered('inst_is')
        if not partners:
            raise UserError('Esta oportunidad no es una cuenta institucional.')
        partners.with_context(inst_engine=True, tracking_disable=True).write(
            {'inst_pinned_date': today, 'inst_skip_date': False})
        self.env['cristal.inst.engine'].recompute(partners)
        return True

    def action_inst_skip_today(self):
        """Sacar esta cuenta de "Mi día": pregunta el motivo, porque de eso depende qué pasa después."""
        self.ensure_one()
        partner = self._inst_partner()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sacar de hoy',
            'res_model': 'cristal.inst.skip.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': partner.id},
        }

    def action_inst_recompute(self):
        self.env['cristal.inst.engine'].recompute(self.mapped('inst_partner_id'))
        return True

    def action_inst_discard(self):
        return self._inst_partner().action_inst_discard()

    def action_inst_reactivate(self):
        return self._inst_partner().action_inst_reactivate()
