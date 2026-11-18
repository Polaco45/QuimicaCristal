from odoo import api, fields, models
from odoo.exceptions import UserError

from .inst_chain import INST_CHAINS

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
    ('whatsapp', 'Le mandé el WhatsApp'),
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

    # --- Cómo entró y cola de trabajo ---------------------------------------
    inst_source = fields.Selection([
        ('alejandra', 'Base que ya se venía trabajando'),
        ('etiqueta', 'Etiqueta EMPRESA'),
        ('criterio', 'La sumó el sistema (empresa que nos compró)'),
        ('manual', 'Carga manual'),
    ], 'Cómo entró', copy=False, index=True)
    inst_review = fields.Boolean(
        'Para revisar', copy=False, index=True,
        help='La sumó el sistema sin que tuviera la etiqueta EMPRESA. Revisar si realmente es institucional.')
    inst_excluded = fields.Boolean(
        'No es institucional', copy=False,
        help='Marcala para sacarla del flujo y que el sistema no la vuelva a sumar.')
    inst_user_id = fields.Many2one('res.users', 'Responsable institucional', copy=False, index=True, readonly=True)
    inst_in_pool = fields.Boolean('En la fila de llamadas', copy=False, index=True, readonly=True)
    inst_queue_date = fields.Date('Día asignado en la fila', copy=False, readonly=True)
    inst_today = fields.Boolean('Es para hoy', copy=False, index=True, readonly=True)
    inst_auto_step_id = fields.Many2one(
        'cristal.inst.chain.step', 'WhatsApp listo para salir solo', copy=False, readonly=True,
        ondelete='set null',
        help='Aviso de la cadena que saldría automáticamente si el número de instituciones estuviera conectado.')

    # --- Cadena de avisos ----------------------------------------------------
    inst_chain = fields.Selection(INST_CHAINS, 'Cadena de avisos', copy=False, readonly=True)
    inst_chain_anchor = fields.Date('La cadena cuenta desde', copy=False, readonly=True)
    inst_chain_done = fields.Integer('Último paso hecho de la cadena', copy=False, readonly=True)
    inst_chain_step_id = fields.Many2one(
        'cristal.inst.chain.step', 'Paso de la cadena', copy=False, readonly=True, ondelete='set null')
    inst_chain_channel = fields.Selection(
        related='inst_chain_step_id.channel', string='Canal del próximo paso', store=True)
    inst_chain_message = fields.Text('Mensaje para mandar', compute='_compute_inst_chain_message')

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
    inst_buys = fields.Char('Qué nos compra', copy=False, readonly=True)
    inst_gaps = fields.Char(
        'Qué le falta sumar', copy=False, readonly=True,
        help='Familias de fabricación propia que todavía no nos compra. Son las que más margen dejan.')
    inst_script = fields.Html('Guion para la llamada', compute='_compute_inst_script', sanitize=False)

    @api.depends('inst_stage', 'inst_alert', 'inst_decisor_id', 'inst_ficha_falta', 'inst_gaps',
                 'inst_last_order', 'inst_kit_date', 'name')
    def _compute_inst_script(self):
        from markupsafe import Markup
        intro = 'Soy Joaquín, de Cristal Limpieza Profesional, somos fábrica acá en Río Cuarto.'
        for partner in self:
            name = partner.name or ''
            who = partner.inst_decisor_id.name or ''
            hello = ('Hola %s, ¿cómo estás?' % who) if who else 'Hola, buen día.'
            lines = []
            stage = partner.inst_stage
            if stage == 'prospecto' or (stage == 'captacion' and not who):
                lines = [
                    '%s %s Seleccionamos a %s entre algunos locales para mandarles sin cargo un kit de productos '
                    'y que prueben la nueva formulación de nuestro desengrasante.' % (hello, intro, name),
                    '¿Quién se encarga de los pedidos de limpieza? ¿Me pasás su nombre y su WhatsApp?',
                ]
            elif stage == 'captacion':
                lines = [
                    '%s %s Les queremos mandar sin cargo un kit con el desengrasante de formulación nueva '
                    'para que lo prueben.' % (hello, intro),
                    '¿Qué detergente y qué lavandina están usando hoy, y cuánto llevan cada vez?',
                    'En papel, ¿usan bobina, toallas o servilletas? ¿Cuánto por semana?',
                    '¿Cada cuánto reponen? ¿A qué dirección y en qué horario les llevo el kit?',
                ]
                if partner.inst_ficha_falta:
                    lines.append('Falta completar: %s.' % partner.inst_ficha_falta)
            elif stage == 'primera_compra':
                lines = [
                    '%s Soy Joaquín, de Cristal. ¿Cómo les fue con el kit, pudieron probar el desengrasante?' % hello,
                    'Les armé una propuesta especial de primera compra con lo que usan todas las semanas.',
                    '¿Te la mando ahora por WhatsApp y lo entregamos esta semana?',
                ]
            elif stage == 'pedido_formal':
                lines = [
                    '%s Soy Joaquín, de Cristal. ¿Cómo les fue con lo que llevaron?' % hello,
                    '¿Ya les toca reponer? Les armo el mismo pedido y lo entregamos.',
                    '¿Cada cuánto les conviene que les avise para reponer?',
                ]
            elif stage == 'recurrente':
                if partner.inst_alert in ('riesgo', 'dormido'):
                    lines = [
                        '%s Soy Joaquín, de Cristal. Hace un tiempo que no nos piden y quería saber cómo están.' % hello,
                        '¿Les quedó stock o hubo algo que no les cerró?',
                        '¿Les armo el pedido de siempre?',
                    ]
                else:
                    lines = ['%s Soy Joaquín, de Cristal. ¿Les armo la reposición de siempre?' % hello]
                    if partner.inst_gaps:
                        lines.append('Todavía no nos llevan: %s. Ofrecer uno para probar en este pedido.'
                                     % partner.inst_gaps)
            if lines:
                html = Markup('<ol>%s</ol>') % Markup('').join(Markup('<li>%s</li>') % line for line in lines)
            else:
                html = False
            partner.inst_script = html

    @api.depends('inst_chain_step_id', 'inst_decisor_id', 'name')
    def _compute_inst_chain_message(self):
        for partner in self:
            step = partner.inst_chain_step_id
            partner.inst_chain_message = step.render_message(partner) if step and step.message else False

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
        if vals.get('inst_excluded'):
            # "No es institucional": sale del flujo y su tarjeta del CRM se archiva
            vals = dict(vals, inst_is=False, inst_today=False, inst_in_pool=False, inst_review=False)
            leads = self.env['crm.lead'].sudo().search(
                [('inst_account', '=', True), ('inst_partner_id', 'in', self.ids)])
            if leads:
                self.env['mail.activity'].sudo().search(
                    [('res_model', '=', 'crm.lead'), ('res_id', 'in', leads.ids),
                     ('automated', '=', True)]).unlink()
                leads.with_context(tracking_disable=True).write({'active': False, 'inst_account': False})
        if (vals.get('inst_is') and 'inst_source' not in vals and not self.env.context.get('inst_engine')
                and not any(self.mapped('inst_source'))):
            vals = dict(vals, inst_source='manual')
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

    def _inst_order_vals(self):
        partner = self.commercial_partner_id
        vals = {'partner_id': partner.id, 'user_id': self.env.uid}
        team = self.env['crm.team'].sudo().search([('name', '=', 'Institucional')], limit=1)
        if team:
            vals['team_id'] = team.id
        lead = self.env['crm.lead'].sudo().search(
            [('partner_id', 'child_of', partner.id), ('type', '=', 'opportunity')], order='id desc', limit=1)
        if lead:
            vals['opportunity_id'] = lead.id
        return vals

    def _inst_open_order(self, order):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
        }

    def action_inst_send_kit(self):
        """Arma el pedido del kit de prueba sin cargo. Queda como cotización para revisarlo y confirmarlo."""
        self.ensure_one()
        partner = self.commercial_partner_id
        if partner.inst_kit_order_id:
            return self._inst_open_order(partner.inst_kit_order_id)
        icp = self.env['ir.config_parameter'].sudo()
        raw = icp.get_param('cristal_institucional.kit_product_ids', '5315,6334,11763')
        ids = [int(x) for x in raw.replace(' ', '').split(',') if x.isdigit()]
        products = self.env['product.product'].browse(ids).exists()
        if not products:
            raise UserError('No están configurados los productos del kit (parámetro cristal_institucional.kit_product_ids).')
        tag_name = icp.get_param('cristal_institucional.kit_tag', 'Regalo captación')
        Tag = self.env['crm.tag'].sudo()
        tag = Tag.search([('name', '=', tag_name)], limit=1) or Tag.create({'name': tag_name})
        vals = partner._inst_order_vals()
        vals.update({
            'client_order_ref': 'Kit de prueba - captación institucional',
            'tag_ids': [(6, 0, tag.ids)],
            'order_line': [(0, 0, {'product_id': p.id, 'product_uom_qty': 1.0, 'price_unit': 0.0})
                           for p in products],
        })
        order = self.env['sale.order'].create(vals)
        order.order_line.write({'price_unit': 0.0})
        self.env['cristal.inst.engine'].recompute(partner)
        return self._inst_open_order(order)

    def action_inst_first_offer(self):
        """Abre una cotización marcada como propuesta de primera compra (con piso de margen)."""
        self.ensure_one()
        partner = self.commercial_partner_id
        vals = partner._inst_order_vals()
        vals.update({
            'client_order_ref': 'Propuesta de primera compra',
            'inst_first_offer': True,
        })
        order = self.env['sale.order'].create(vals)
        return self._inst_open_order(order)

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
