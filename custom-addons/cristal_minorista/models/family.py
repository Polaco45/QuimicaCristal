# -*- coding: utf-8 -*-
from odoo import fields, models


class CristalCfFamily(models.Model):
    _name = 'cristal.cf.family'
    _description = 'Familia de producto para el ciclo de consumo'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    match_pattern = fields.Char(string='Palabras del nombre', required=True,
                                help='Partes del nombre del producto, separadas por |. '
                                     'Ej.: "lavandina" o "jabon b/e|jabon liq".')
    population_cycle_days = fields.Integer(string='Ciclo general (días)', readonly=True,
                                           help='Mediana de todos los clientes; se usa para quien '
                                                'todavía no tiene historia propia.')
    product_count = fields.Integer(string='Productos', readonly=True)
    active = fields.Boolean(default=True)

    def _patterns(self):
        self.ensure_one()
        return [p.strip().lower() for p in (self.match_pattern or '').split('|') if p.strip()]


class CristalCfCycle(models.Model):
    _name = 'cristal.cf.cycle'
    _description = 'Ciclo de consumo de un cliente para una familia de producto'
    _order = 'next_due_date'

    partner_id = fields.Many2one('res.partner', required=True, index=True, ondelete='cascade')
    family_id = fields.Many2one('cristal.cf.family', required=True, index=True, ondelete='cascade')
    purchases = fields.Integer(string='Compras')
    last_date = fields.Date(string='Última compra')
    last_qty = fields.Float(string='Cantidad última compra')
    cycle_days = fields.Integer(string='Ciclo (días)')
    cycle_source = fields.Selection([('personal', 'Propio'), ('general', 'General')], string='Ciclo')
    next_due_date = fields.Date(string='Se le termina aprox.', index=True)
    customer_type = fields.Selection(related='partner_id.cristal_customer_type', store=True)
    mkt_allowed = fields.Boolean(related='partner_id.cristal_mkt_allowed')
    wa_key = fields.Char(related='partner_id.cristal_wa_key')
