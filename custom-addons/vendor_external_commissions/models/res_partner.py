from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    commission_owner_id = fields.Many2one(
        'res.users',
        string='Vendedor captador actual',
        help='Vendedor que actualmente recibe la comisión de este cliente.',
        copy=False,
    )
    commission_cycle_start_date = fields.Date(
        string='Inicio ciclo comisión',
        copy=False,
    )
    commission_cycle_end_date = fields.Date(
        string='Fin ciclo 20%',
        copy=False,
        help='Último día del tramo al 20%. Luego el cliente sigue al 5% hasta una reactivación.',
    )
    commission_first_move_id = fields.Many2one(
        'account.move',
        string='Primera factura del ciclo actual',
        copy=False,
    )
    last_positive_invoice_date = fields.Date(
        string='Última compra positiva',
        copy=False,
        help='Última fecha de factura positiva publicada del cliente.',
    )
    commission_cycle_state = fields.Selection(
        selection=[
            ('new', 'Nuevo / Reactivado'),
            ('recurrent', 'Recurrente 5%'),
        ],
        string='Estado comercial actual',
        default='new',
        copy=False,
    )
