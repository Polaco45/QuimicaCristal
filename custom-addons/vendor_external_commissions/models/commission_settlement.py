from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CommissionSettlement(models.Model):
    _name = 'commission.settlement'
    _description = 'Liquidación de comisiones'
    _order = 'cutoff_date desc, id desc'

    name = fields.Char(
        string='Liquidación',
        required=True,
        copy=False,
        default=lambda self: _('Nueva'),
    )
    user_id = fields.Many2one(
        'res.users',
        string='Vendedor',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        string='Moneda compañía',
        readonly=True,
    )
    cutoff_date = fields.Date(
        string='Fecha de corte',
        required=True,
        default=fields.Date.context_today,
        help='Se cargarán todas las facturas/notas de crédito pendientes hasta esta fecha.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('confirmed', 'Confirmada'),
            ('cancelled', 'Cancelada'),
        ],
        default='draft',
        required=True,
    )
    line_ids = fields.One2many(
        'commission.settlement.line',
        'settlement_id',
        string='Líneas',
        copy=False,
    )
    total_base_amount = fields.Monetary(
        string='Base total',
        currency_field='company_currency_id',
        compute='_compute_totals',
        store=True,
    )
    total_commission_amount = fields.Monetary(
        string='Comisión total',
        currency_field='company_currency_id',
        compute='_compute_totals',
        store=True,
    )
    move_count = fields.Integer(
        string='Comprobantes',
        compute='_compute_totals',
        store=True,
    )

    @api.depends('line_ids.base_amount', 'line_ids.commission_amount', 'line_ids.move_id')
    def _compute_totals(self):
        for settlement in self:
            settlement.total_base_amount = sum(settlement.line_ids.mapped('base_amount'))
            settlement.total_commission_amount = sum(settlement.line_ids.mapped('commission_amount'))
            settlement.move_count = len(settlement.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nueva')) == _('Nueva'):
                vals['name'] = self.env['ir.sequence'].next_by_code('commission.settlement') or _('Nueva')
        return super().create(vals_list)

    def _pending_move_domain(self):
        self.ensure_one()
        return [
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('state', '=', 'posted'),
            ('commission_applicable', '=', True),
            ('commission_settled', '=', False),
            ('commission_manual_review', '=', False),
            ('commission_owner_id', '=', self.user_id.id),
            ('company_id', '=', self.company_id.id),
            ('invoice_date', '<=', self.cutoff_date),
        ]

    def action_load_pending_moves(self):
        for settlement in self:
            if settlement.state != 'draft':
                raise UserError(_('Solo podés cargar comprobantes en una liquidación en borrador.'))
            settlement.line_ids.unlink()
            moves = self.env['account.move'].search(settlement._pending_move_domain(), order='invoice_date asc, id asc')
            line_commands = []
            for move in moves:
                line_commands.append((0, 0, {
                    'move_id': move.id,
                    'partner_id': move.partner_id.commercial_partner_id.id,
                    'invoice_date': move.invoice_date,
                    'rate': move.commission_rate,
                    'base_amount': move.commission_base_amount,
                    'commission_amount': move.commission_amount,
                }))
            settlement.write({'line_ids': line_commands})
        return True

    def action_confirm(self):
        for settlement in self:
            if settlement.state != 'draft':
                raise UserError(_('Solo podés confirmar una liquidación en borrador.'))
            if not settlement.line_ids:
                raise UserError(_('No hay líneas para liquidar.'))
            moves = settlement.line_ids.mapped('move_id')
            already_settled = moves.filtered('commission_settled')
            if already_settled:
                raise UserError(_('Hay comprobantes que ya fueron liquidados: %s') % ', '.join(already_settled.mapped('name')))
            moves.write({
                'commission_settled': True,
                'commission_settlement_id': settlement.id,
                'commission_settlement_date': fields.Date.context_today(self),
            })
            settlement.state = 'confirmed'
        return True

    def action_reset_to_draft(self):
        for settlement in self:
            if settlement.state != 'confirmed':
                continue
            moves = settlement.line_ids.mapped('move_id').filtered(lambda m: m.commission_settlement_id == settlement)
            moves.write({
                'commission_settled': False,
                'commission_settlement_id': False,
                'commission_settlement_date': False,
            })
            settlement.state = 'draft'
        return True

    def action_cancel(self):
        for settlement in self:
            if settlement.state == 'confirmed':
                raise UserError(_('Primero devolvé la liquidación a borrador para poder cancelarla.'))
            settlement.state = 'cancelled'
        return True

    def action_view_moves(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Comprobantes liquidación'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.line_ids.mapped('move_id').ids)],
            'context': {'create': False},
        }


class CommissionSettlementLine(models.Model):
    _name = 'commission.settlement.line'
    _description = 'Línea de liquidación de comisiones'
    _order = 'invoice_date asc, id asc'

    settlement_id = fields.Many2one(
        'commission.settlement',
        string='Liquidación',
        required=True,
        ondelete='cascade',
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        related='settlement_id.company_currency_id',
        readonly=True,
    )
    move_id = fields.Many2one(
        'account.move',
        string='Comprobante',
        required=True,
        ondelete='restrict',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        required=True,
        ondelete='restrict',
    )
    invoice_date = fields.Date(
        string='Fecha',
        required=True,
    )
    rate = fields.Float(
        string='Tasa (%)',
        digits=(16, 2),
        required=True,
    )
    base_amount = fields.Monetary(
        string='Base',
        currency_field='company_currency_id',
        required=True,
    )
    commission_amount = fields.Monetary(
        string='Comisión',
        currency_field='company_currency_id',
        required=True,
    )

    _sql_constraints = [
        ('settlement_move_unique', 'unique(settlement_id, move_id)', 'No podés repetir el mismo comprobante en una liquidación.'),
    ]
