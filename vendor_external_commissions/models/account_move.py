from datetime import timedelta
from dateutil.relativedelta import relativedelta

from odoo import _, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    commission_applicable = fields.Boolean(
        string='Comisión aplicable',
        copy=False,
        help='Indica si este comprobante entra en el esquema de comisión.',
    )
    commission_rate = fields.Float(
        string='Tasa comisión (%)',
        digits=(16, 2),
        copy=False,
    )
    commission_base_amount = fields.Monetary(
        string='Base comisión',
        currency_field='company_currency_id',
        copy=False,
        help='Base en moneda de la compañía, sin impuestos.',
    )
    commission_amount = fields.Monetary(
        string='Importe comisión',
        currency_field='company_currency_id',
        copy=False,
        help='Importe de comisión a liquidar. Las notas de crédito van en negativo.',
    )
    commission_owner_id = fields.Many2one(
        'res.users',
        string='Vendedor comisionado',
        copy=False,
    )
    commission_cycle_start_date = fields.Date(
        string='Inicio ciclo comisión',
        copy=False,
    )
    commission_cycle_end_date = fields.Date(
        string='Fin ciclo 20%',
        copy=False,
    )
    commission_source_move_id = fields.Many2one(
        'account.move',
        string='Factura origen comisión',
        copy=False,
        help='Usado principalmente en notas de crédito para copiar la tasa de la factura original.',
    )
    commission_settled = fields.Boolean(
        string='Comisión liquidada',
        copy=False,
    )
    commission_settlement_id = fields.Many2one(
        'commission.settlement',
        string='Liquidación de comisión',
        copy=False,
    )
    commission_settlement_date = fields.Date(
        string='Fecha liquidación comisión',
        copy=False,
    )
    commission_manual_review = fields.Boolean(
        string='Revisión manual comisión',
        copy=False,
        help='Se activa si el comprobante necesita una revisión manual antes de liquidar comisión.',
    )

    def _is_customer_commission_move(self):
        self.ensure_one()
        return self.move_type in ('out_invoice', 'out_refund')

    def _company_round(self, amount):
        self.ensure_one()
        currency = self.company_currency_id or self.company_id.currency_id
        return currency.round(amount)

    def _get_effective_invoice_date(self):
        self.ensure_one()
        return self.invoice_date or fields.Date.context_today(self)

    def _get_commission_partner(self):
        self.ensure_one()
        return self.partner_id.commercial_partner_id

    def _get_effective_salesperson(self):
        self.ensure_one()
        commission_partner = self._get_commission_partner()
        return self.invoice_user_id or commission_partner.commission_owner_id or self.env.user

    def _get_previous_positive_invoice(self):
        self.ensure_one()
        invoice_date = self._get_effective_invoice_date()
        commission_partner = self._get_commission_partner()

        domain = [
            ('partner_id.commercial_partner_id', '=', commission_partner.id),
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'posted'),
            ('move_type', '=', 'out_invoice'),
            ('id', '!=', self.id),
            '|',
                ('invoice_date', '<', invoice_date),
                '&', ('invoice_date', '=', invoice_date), ('id', '<', self.id),
        ]
        return self.search(domain, order='invoice_date desc, id desc', limit=1)

    def _build_invoice_commission_values(self):
        self.ensure_one()
        invoice_date = self._get_effective_invoice_date()
        previous_invoice = self._get_previous_positive_invoice()
        salesperson = self._get_effective_salesperson()
        commission_partner = self._get_commission_partner()

        new_cycle = False

        # Caso 1: nunca compró la empresa madre
        if not previous_invoice:
            new_cycle = True
        else:
            # Caso 2: reactivación luego de 6 meses o más sin compras
            previous_date = previous_invoice._get_effective_invoice_date()
            reactivation_date = previous_date + relativedelta(months=6)
            if invoice_date >= reactivation_date:
                new_cycle = True

        if new_cycle:
            cycle_start = invoice_date
            cycle_end = invoice_date + timedelta(days=29)
            owner = salesperson
            first_move_id = self.id
            rate = 20.0
        else:
            cycle_start = (
                commission_partner.commission_cycle_start_date
                or previous_invoice.commission_cycle_start_date
                or previous_invoice._get_effective_invoice_date()
            )
            cycle_end = (
                commission_partner.commission_cycle_end_date
                or previous_invoice.commission_cycle_end_date
                or (cycle_start + timedelta(days=29))
            )
            owner = (
                commission_partner.commission_owner_id
                or previous_invoice.commission_owner_id
                or previous_invoice.invoice_user_id
                or salesperson
            )
            first_move_id = (
                commission_partner.commission_first_move_id.id
                or previous_invoice.id
            )

            # Solo 20% si está dentro de la ventana activa ya abierta
            if invoice_date <= cycle_end:
                rate = 20.0
            else:
                rate = 5.0

        base_amount = abs(self.amount_untaxed_signed)
        commission_amount = self._company_round(base_amount * (rate / 100.0))

        values = {
            'commission_applicable': True,
            'commission_rate': rate,
            'commission_base_amount': base_amount,
            'commission_amount': commission_amount,
            'commission_owner_id': owner.id if owner else False,
            'commission_cycle_start_date': cycle_start,
            'commission_cycle_end_date': cycle_end,
            'commission_source_move_id': False,
            'commission_manual_review': False,
            '__new_cycle': new_cycle,
            '__partner_first_move_id': first_move_id,
        }
        return values

    def _build_refund_commission_values(self):
        self.ensure_one()
        source_move = self.reversed_entry_id

        if not source_move or not source_move.commission_applicable:
            return {
                'commission_applicable': False,
                'commission_rate': 0.0,
                'commission_base_amount': 0.0,
                'commission_amount': 0.0,
                'commission_owner_id': False,
                'commission_cycle_start_date': False,
                'commission_cycle_end_date': False,
                'commission_source_move_id': source_move.id if source_move else False,
                'commission_manual_review': True,
            }

        rate = source_move.commission_rate or 0.0
        base_amount = self.amount_untaxed_signed
        if base_amount > 0:
            base_amount = -abs(base_amount)
        commission_amount = self._company_round(base_amount * (rate / 100.0))

        return {
            'commission_applicable': True,
            'commission_rate': rate,
            'commission_base_amount': base_amount,
            'commission_amount': commission_amount,
            'commission_owner_id': source_move.commission_owner_id.id,
            'commission_cycle_start_date': source_move.commission_cycle_start_date,
            'commission_cycle_end_date': source_move.commission_cycle_end_date,
            'commission_source_move_id': source_move.id,
            'commission_manual_review': False,
        }

    def _update_partner_commission_cache(self, values):
        self.ensure_one()
        partner = self._get_commission_partner()

        vals = {
            'commission_owner_id': values.get('commission_owner_id') or False,
            'commission_cycle_start_date': values.get('commission_cycle_start_date') or False,
            'commission_cycle_end_date': values.get('commission_cycle_end_date') or False,
            'last_positive_invoice_date': self._get_effective_invoice_date(),
            'commission_cycle_state': (
                'new'
                if self._get_effective_invoice_date() <= (
                    values.get('commission_cycle_end_date') or self._get_effective_invoice_date()
                )
                else 'recurrent'
            ),
        }

        first_move_id = values.get('__partner_first_move_id')
        if first_move_id:
            vals['commission_first_move_id'] = first_move_id

        partner.write(vals)

    def _apply_commission_logic(self):
        for move in self:
            if move.state != 'posted' or not move._is_customer_commission_move():
                continue

            if move.move_type == 'out_invoice':
                values = move._build_invoice_commission_values()
                internal_values = {
                    key: value for key, value in values.items() if not key.startswith('__')
                }
                move.write(internal_values)
                move._update_partner_commission_cache(values)

            elif move.move_type == 'out_refund':
                values = move._build_refund_commission_values()
                move.write(values)

    def action_post(self):
        res = super().action_post()
        commission_moves = self.filtered(
            lambda m: m.state == 'posted' and m.move_type in ('out_invoice', 'out_refund')
        )
        ordered_moves = commission_moves.sorted(
            key=lambda m: (
                m._get_effective_invoice_date(),
                m.id,
                0 if m.move_type == 'out_invoice' else 1,
            )
        )
        ordered_moves._apply_commission_logic()
        return res

    def action_recompute_commission(self):
        for move in self:
            if move.state != 'posted':
                raise UserError(_('Solo se puede recalcular la comisión de comprobantes publicados.'))
            if move.commission_settled:
                raise UserError(_('No se puede recalcular una comisión ya liquidada.'))
            if not move._is_customer_commission_move():
                raise UserError(_('Solo se pueden recalcular comisiones en facturas o notas de crédito de cliente.'))

        self._apply_commission_logic()
        return True