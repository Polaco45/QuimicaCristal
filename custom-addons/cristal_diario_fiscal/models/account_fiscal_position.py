# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.osv import expression


class AccountFiscalPosition(models.Model):
    _inherit = 'account.fiscal.position'

    cristal_sale_journal_id = fields.Many2one(
        'account.journal', string='Diario de venta',
        domain="[('type', '=', 'sale'), ('company_id', '=', company_id)]",
        check_company=True,
        help='Diario con el que se factura a los clientes con esta posición fiscal '
             '(POS, órdenes de venta y facturas). Vacío: no se fuerza ningún diario.',
    )
    cristal_requires_afip = fields.Boolean(
        string='Exige responsabilidad AFIP', compute='_compute_cristal_requires_afip',
        help='Es la posición de los clientes con responsabilidad AFIP (factura '
             'electrónica): en la caja no se puede elegir para un cliente sin esos datos.',
    )

    def _compute_cristal_requires_afip(self):
        for position in self:
            position.cristal_requires_afip = (
                position.company_id.cristal_responsible_fiscal_position_id == position)

    @api.model
    def _load_pos_data_domain(self, data):
        # La caja necesita todas las posiciones que tienen uno de sus diarios,
        # para poder pasar de una a otra desde la pantalla de cobro.
        domain = super()._load_pos_data_domain(data)
        config = self.env['pos.config'].browse(data['pos.config']['data'][0]['id'])
        journals = config.invoice_journal_ids
        if not journals:
            return domain
        return expression.OR([domain, [
            ('cristal_sale_journal_id', 'in', journals.ids),
            ('company_id', '=', config.company_id.id),
        ]])

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        if fields_list:
            fields_list += ['cristal_sale_journal_id', 'cristal_requires_afip']
        return fields_list
