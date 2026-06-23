# -*- coding: utf-8 -*-
"""
Línea del Combo Emprendedor.

El "Combo Emprendedor" es un combo fijo prearmado que el bot ofrece a los
clientes que están ARRANCANDO. Se define en la config del agente (un combo,
con sus productos y cantidades). El bot lo cotiza con create_sale_order.
"""
from odoo import models, fields


class CristalAgentComboLine(models.Model):
    _name = 'cristal.agent.combo.line'
    _description = "Cristal Agent — Línea del Combo Emprendedor"
    _order = 'sequence, id'

    config_id = fields.Many2one(
        'cristal.agent.config',
        string="Configuración",
        ondelete='cascade',
        required=True,
    )
    sequence = fields.Integer(string="Secuencia", default=10)
    product_id = fields.Many2one(
        'product.product',
        string="Producto",
        required=True,
        domain=[('sale_ok', '=', True)],
    )
    qty = fields.Float(string="Cantidad", default=1.0, required=True)
    uom_name = fields.Char(
        related='product_id.uom_id.name',
        string="Unidad",
        readonly=True,
    )
