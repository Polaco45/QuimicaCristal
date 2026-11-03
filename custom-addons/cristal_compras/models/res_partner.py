# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    cristal_buy_channel = fields.Selection(
        [('whatsapp', "WhatsApp"), ('email', "Mail")], string="Canal para pedidos",
        help="Por dónde le manda el agente de Compras las órdenes y pedidos de precio. "
             "Vacío: WhatsApp si tiene celular, si no mail.")
    cristal_price_list_exempt = fields.Boolean(
        string="No pedir lista del mes",
        help="El primer lunes de cada mes no se le pide la lista de precios.")
    cristal_price_list_mode = fields.Selection(
        [('list', "Lista completa"), ('raw', "Listado de materias primas para cotizar")],
        string="Pedido mensual", default='list')
    cristal_price_list_date = fields.Date(
        string="Última lista recibida", readonly=True)
    cristal_price_list_ids = fields.One2many(
        'cristal.compras.price.list', 'partner_id', string="Listas de precios recibidas")

    def _cristal_raw_materials(self):
        """Productos que le compramos a este proveedor en los últimos 18 meses."""
        self.ensure_one()
        lines = self.env['purchase.order.line'].sudo().search([
            ('partner_id', 'child_of', self.commercial_partner_id.id),
            ('order_id.state', 'in', ['purchase', 'done']),
            ('date_order', '>=', fields.Datetime.subtract(fields.Datetime.now(), months=18)),
            ('product_id', '!=', False),
        ])
        return lines.mapped('product_id').sorted('display_name')
