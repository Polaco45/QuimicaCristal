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
        # La comisión SIEMPRE sigue al vendedor de ESTA factura
        return self.invoice_user_id or self.env.user

    def _get_previous_positive_invoice(self):
        self.ensure_one()
        invoice_date = self._get_effective_invoice_date()
        commission_partner = self._get_commission_partner()

        domain = [
            ('partner_id', 'child_of', commission_partner.id),
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

        # 1) Nunca compró antes => nuevo ciclo al 20%
        if not previous_invoice:
            new_cycle = True

        # 2) Reactivación real => 6 meses o más sin compras
        else:
            previous_date = previous_invoice._get_effective_invoice_date()
            reactivation_date = previous_date + relativedelta(months=6)
            if invoice_date >= reactivation_date:
                new_cycle = True

        if new_cycle:
            cycle_start = invoice_date
            cycle_end = invoice_date + timedelta(days=29)
            rate = 20.0
            first_move_id = self.id

        else:
            # Solo usamos la metadata del ciclo para definir la tasa.
            # NO usamos más el vendedor guardado en el partner para definir comisión.
            known_cycle_start = (
                commission_partner.commission_cycle_start_date
                or previous_invoice.commission_cycle_start_date
            )
            known_cycle_end = (
                commission_partner.commission_cycle_end_date
                or previous_invoice.commission_cycle_end_date
            )

            # Si existe un ciclo ya abierto, lo respetamos
            if known_cycle_start and known_cycle_end:
                cycle_start = known_cycle_start
                cycle_end = known_cycle_end
                rate = 20.0 if invoice_date <= cycle_end else 5.0
                first_move_id = (
                    commission_partner.commission_first_move_id.id
                    or previous_invoice.id
                )
            else:
                # Cliente histórico/recurrente sin ciclo activo
                cycle_start = False
                cycle_end = False
                rate = 5.0
                first_move_id = False

        base_amount = abs(self.amount_untaxed_signed)
        commission_amount = self._company_round(base_amount * (rate / 100.0))

        values = {
            'commission_applicable': True,
            'commission_rate': rate,
            'commission_base_amount': base_amount,
            'commission_amount': commission_amount,
            'commission_owner_id': salesperson.id if salesperson else False,
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
        invoice_date = self._get_effective_invoice_date()

        vals = {
            'last_positive_invoice_date': invoice_date,
            # Informativo: dejamos en el partner el último vendedor que está manejando ese cliente
            'commission_owner_id': values.get('commission_owner_id') or False,
        }

        if values.get('__new_cycle'):
            vals.update({
                'commission_cycle_start_date': values.get('commission_cycle_start_date') or False,
                'commission_cycle_end_date': values.get('commission_cycle_end_date') or False,
                'commission_cycle_state': 'new',
            })
            first_move_id = values.get('__partner_first_move_id')
            if first_move_id:
                vals['commission_first_move_id'] = first_move_id

        else:
            if values.get('commission_cycle_start_date') and values.get('commission_cycle_end_date'):
                vals.update({
                    'commission_cycle_start_date': values.get('commission_cycle_start_date'),
                    'commission_cycle_end_date': values.get('commission_cycle_end_date'),
                    'commission_cycle_state': (
                        'new'
                        if invoice_date <= values.get('commission_cycle_end_date')
                        else 'recurrent'
                    ),
                })
                first_move_id = values.get('__partner_first_move_id')
                if first_move_id:
                    vals['commission_first_move_id'] = first_move_id
            else:
                vals.update({
                    'commission_cycle_start_date': False,
                    'commission_cycle_end_date': False,
                    'commission_cycle_state': 'recurrent',
                })

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