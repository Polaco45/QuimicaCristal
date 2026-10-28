# -*- coding: utf-8 -*-
from odoo import fields, models


class CristalFidTouch(models.Model):
    _name = 'cristal.fid.touch'
    _description = 'Fidelización — contacto con un cliente'
    _order = 'date desc, id desc'

    partner_id = fields.Many2one('res.partner', required=True, index=True, ondelete='cascade')
    flow_id = fields.Many2one('cristal.fid.flow', required=True, index=True, ondelete='cascade')
    flow_code = fields.Char(related='flow_id.code', store=True, index=True)
    date = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    state = fields.Selection([
        ('dry_run', 'Prueba (no enviado)'),
        ('holdout', 'Grupo de control'),
        ('sent', 'Enviado'),
        ('error', 'Error'),
    ], required=True, index=True)
    error = fields.Char()
    variables = fields.Char(string='Variables')
    family_id = fields.Many2one('cristal.cf.family', string='Familia')
    ref_date = fields.Date(string='Compra de referencia',
                           help='Fecha de la compra que disparó el contacto (para no repetirlo).')
    wa_message_id = fields.Many2one('whatsapp.message', string='Mensaje')
    reply = fields.Selection([('positive', 'Sí / bien'), ('negative', 'No / mal'),
                              ('optout', 'Pidió la baja'), ('other', 'Otra respuesta')],
                             string='Respuesta', index=True)
    reply_text = fields.Char(string='Texto de la respuesta')
    reply_date = fields.Datetime(string='Fecha de la respuesta')
    sale_order_id = fields.Many2one('sale.order', string='Pedido generado')
    review_requested = fields.Boolean(string='Se le pidió reseña en Google')
    converted = fields.Boolean(string='Compró después', index=True,
                               help='Compró en cualquier canal dentro de los 14 días siguientes.')
    converted_date = fields.Date(string='Fecha de la compra')
    converted_amount = fields.Monetary(string='Monto de la compra', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
