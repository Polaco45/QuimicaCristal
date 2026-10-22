# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountFiscalPosition(models.Model):
    _inherit = 'account.fiscal.position'

    cristal_sale_journal_id = fields.Many2one(
        'account.journal', string='Diario de venta',
        domain="[('type', '=', 'sale'), ('company_id', '=', company_id)]",
        check_company=True,
        help='Diario con el que se factura a los clientes con esta posición fiscal '
             '(POS, órdenes de venta y facturas). Vacío: no se fuerza ningún diario.',
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        if fields_list:
            fields_list.append('cristal_sale_journal_id')
        return fields_list
