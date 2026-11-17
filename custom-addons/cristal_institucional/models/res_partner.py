from odoo import api, fields, models

INST_STAGES = [
    ('prospecto', 'Prospecto'),
    ('captacion', '1 · Captación'),
    ('primera_compra', '2 · Primera compra'),
    ('pedido_formal', '3 · Pedido formal'),
    ('recurrente', '4 · Recurrente'),
    ('descartado', 'Descartado'),
]

INST_ALERTS = [
    ('ok', 'Al día'),
    ('vence', 'Fecha límite vencida'),
    ('riesgo', 'En riesgo'),
    ('dormido', 'Dormido'),
]

INST_FRECUENCIAS = [
    ('semanal', 'Semanal'),
    ('quincenal', 'Quincenal'),
    ('mensual', 'Mensual'),
    ('bimestral', 'Cada dos meses'),
    ('ocasional', 'Ocasional'),
]


CALL_RESULTS = [
    ('no_atendio', 'No atendió'),
    ('contacto', 'Atendió otra persona: conseguí el contacto de quien decide'),
    ('decisor', 'Hablé con quien decide'),
    ('kit', 'Hablé con quien decide y acepta el kit'),
    ('posponer', 'Me pidió que lo llame más adelante'),
    ('pedido', 'Hizo un pedido'),
    ('no_califica', 'No califica o no le interesa'),
]


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # --- Marca y etapa (las calcula cristal.inst.engine) ---------------------
    inst_is = fields.Boolean(
        'Cliente institucional', index=True, copy=False,
        help='Empresa que compra para consumo propio. Entra a la máquina de venta institucional.')
    inst_stage = fields.Selection(
        INST_STAGES, 'Etapa institucional', index=True, copy=False, readonly=True,
        group_expand='_group_expand_inst_stage')
    inst_stage_date = fields.Date('En la etapa desde', copy=False, readonly=True)
    inst_stage_days = fields.Integer('Días en la etapa', compute='_compute_inst_stage_days')
    inst_reason = fields.Char('Por qué está en esta etapa', copy=False, readonly=True)
    inst_alert = fields.Selection(INST_ALERTS, 'Alerta', index=True, copy=False, readonly=True)

    # --- Próximo paso --------------------------------------------------------
    inst_next_step = fields.Char('Próximo paso', copy=False, readonly=True)
    inst_next_step_date = fields.Date('Fecha del próximo paso', index=True, copy=False, readonly=True)
    inst_deadline = fields.Date('Fecha límite', copy=False, readonly=True)
    inst_postponed_until = fields.Date(
        'Pospuesto hasta', copy=False,
        help='Si el cliente pide que lo llamemos más adelante, poné acá la nueva fecha. '
             'El próximo paso y la fecha límite se corren hasta ese día.')

    inst_priority = fields.Float(
        'Prioridad', index=True, copy=False, readonly=True,
        help='Ordena "Mi día": primero lo que más vale y lo que está por perderse.')

    # --- Llamadas ------------------------------------------------------------
    inst_call_ids = fields.One2many('cristal.inst.call', 'partner_id', 'Contactos registrados')
    inst_attempts = fields.Integer('Intentos sin respuesta', copy=False, readonly=True)
    inst_last_call = fields.Date('Último contacto', copy=False, readonly=True)
    inst_last_result = fields.Selection(CALL_RESULTS, 'Resultado del último contacto', copy=False, readonly=True)

    # --- Ficha de cuenta -----------------------------------------------------
    inst_contactado = fields.Date(
        'Primer contacto', copy=False,
        help='Día en que hablamos por primera vez con alguien de la empresa.')
    inst_decisor_id = fields.Many2one(
        'res.partner', 'Quién decide las compras', copy=False,
        domain="[('parent_id', '=', id)]",
        help='Contacto de la empresa que hace los pedidos.')
    inst_decisor_phone = fields.Char('WhatsApp de quien decide', compute='_compute_inst_decisor_phone')
    inst_productos = fields.Text('Qué productos usan y cuánto')
    inst_proveedor = fields.Char('A quién le compran hoy')
    inst_frecuencia = fields.Selection(INST_FRECUENCIAS, 'Cada cuánto compran')
    inst_entrega_horario = fields.Char('Horario de entrega')
    inst_ficha_pct = fields.Integer('Ficha completa (%)', compute='_compute_inst_ficha')
    inst_ficha_falta = fields.Char('Falta en la ficha', compute='_compute_inst_ficha')

    # --- Kit de prueba -------------------------------------------------------
    inst_kit_order_id = fields.Many2one('sale.order', 'Pedido del kit', copy=False, readonly=True)
    inst_kit_date = fields.Date(
        'Kit entregado el', copy=False,
        help='Se completa solo cuando se valida la entrega del kit. Se puede cargar a mano.')

    # --- Descarte ------------------------------------------------------------
    inst_discarded = fields.Boolean('Descartado', copy=False)
    inst_discard_reason = fields.Char('Motivo del descarte', copy=False)

    # --- Indicadores de la cuenta --------------------------------------------
    inst_order_count = fields.Integer('Compras', copy=False, readonly=True)
    inst_first_order = fields.Date('Primera compra', copy=False, readonly=True)
    inst_last_order = fields.Date('Última compra', copy=False, readonly=True)
    inst_amount_12m = fields.Monetary('Venta 12 meses (sin IVA)', copy=False, readonly=True)
    inst_margin_12m = fields.Monetary('Margen 12 meses', copy=False, readonly=True)
    inst_margin_month = fields.Monetary('Margen por mes', copy=False, readonly=True)
    inst_margin_pct = fields.Float('% de margen', copy=False, readonly=True, digits=(5, 1))
    inst_cycle_days = fields.Integer('Compra cada (días)', copy=False, readonly=True)
    inst_next_expected = fields.Date('Próxima compra esperada', copy=False, readonly=True)
    inst_days_late = fields.Integer('Días de atraso', copy=False, readonly=True)
    inst_computed_at = fields.Datetime('Calculado el', copy=False, readonly=True)

    @api.model
    def _group_expand_inst_stage(self, values, domain):
        return [key for key, _label in INST_STAGES if key != 'descartado' or 'descartado' in values]

    @api.depends('inst_stage_date')
    def _compute_inst_stage_days(self):
        today = fields.Date.context_today(self)
        for partner in self:
            partner.inst_stage_days = (today - partner.inst_stage_date).days if partner.inst_stage_date else 0

    @api.depends('inst_decisor_id.mobile', 'inst_decisor_id.phone')
    def _compute_inst_decisor_phone(self):
        for partner in self:
            decisor = partner.inst_decisor_id
            partner.inst_decisor_phone = decisor.mobile or decisor.phone or False

    @api.depends('industry_id', 'inst_decisor_id', 'inst_decisor_id.mobile', 'inst_decisor_id.phone',
                 'inst_productos', 'inst_proveedor', 'inst_frecuencia', 'street', 'inst_entrega_horario')
    def _compute_inst_ficha(self):
        for partner in self:
            decisor = partner.inst_decisor_id
            checks = [
                ('rubro', bool(partner.industry_id)),
                ('quién decide', bool(decisor)),
                ('WhatsApp de quien decide', bool(decisor and (decisor.mobile or decisor.phone))),
                ('qué productos usan', bool((partner.inst_productos or '').strip())),
                ('a quién le compran', bool((partner.inst_proveedor or '').strip())),
                ('cada cuánto compran', bool(partner.inst_frecuencia)),
                ('dirección', bool((partner.street or '').strip())),
                ('horario de entrega', bool((partner.inst_entrega_horario or '').strip())),
            ]
            missing = [label for label, ok in checks if not ok]
            partner.inst_ficha_pct = round(100 * (len(checks) - len(missing)) / len(checks))
            partner.inst_ficha_falta = ', '.join(missing) if missing else False

    def write(self, vals):
        res = super().write(vals)
        triggers = {'inst_is', 'inst_decisor_id', 'inst_contactado', 'inst_kit_date',
                    'inst_discarded', 'inst_postponed_until'}
        if triggers & set(vals) and not self.env.context.get('inst_engine'):
            self.env['cristal.inst.engine'].recompute(self.filtered('inst_is'))
        return res

    def action_inst_recompute(self):
        self.env['cristal.inst.engine'].recompute(self)
        return True

    def action_inst_call(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Registrar llamada',
            'res_model': 'cristal.inst.call.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.commercial_partner_id.id},
        }

    def action_inst_discard(self):
        self.write({'inst_discarded': True})
        return True

    def action_inst_reactivate(self):
        self.write({'inst_discarded': False, 'inst_discard_reason': False})
        return True

    def action_inst_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pedidos de %s' % self.display_name,
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('partner_id', 'child_of', self.commercial_partner_id.id),
                       ('state', 'in', ('sale', 'done'))],
        }
