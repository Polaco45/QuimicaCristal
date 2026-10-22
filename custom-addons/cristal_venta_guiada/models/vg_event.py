# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CristalVgEvent(models.Model):
    _name = 'cristal.vg.event'
    _description = 'Venta guiada — sugerencia mostrada/aceptada'
    _order = 'id desc'

    date = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user, required=True)
    config_id = fields.Many2one('pos.config', string='Caja')
    order_uuid = fields.Char(string='Ticket (uuid)', index=True)
    trigger_product_id = fields.Many2one('product.product', string='Producto cargado', index=True)
    product_id = fields.Many2one('product.product', string='Producto sugerido', index=True)
    kind = fields.Selection([
        ('combo', 'Combo'),
        ('size', 'Tamaño mayor'),
        ('complement', 'Complemento'),
        ('category', 'Respaldo categoría'),
        ('manual', 'Fijada a mano'),
        ('checkout', 'Producto de caja'),
    ], string='Tipo')
    accepted = fields.Boolean(string='Aceptada')
    amount = fields.Float(string='Monto sumado')

    @api.model
    def log_events(self, events):
        """Lo llama el POS. Cada evento: {config_id, order_uuid, trigger_product_id,
        product_id, kind, accepted, amount}. 'shown' y 'accepted' llegan por separado:
        al aceptar se marca el evento mostrado del mismo ticket y producto."""
        kinds = dict(self._fields['kind'].selection)
        for ev in events or []:
            vals = {
                'config_id': ev.get('config_id') or False,
                'order_uuid': ev.get('order_uuid') or False,
                'trigger_product_id': ev.get('trigger_product_id') or False,
                'product_id': ev.get('product_id') or False,
                'kind': ev.get('kind') if ev.get('kind') in kinds else False,
            }
            if ev.get('accepted'):
                shown = self.search([
                    ('order_uuid', '=', vals['order_uuid']),
                    ('product_id', '=', vals['product_id']),
                    ('accepted', '=', False),
                ], limit=1)
                if shown:
                    shown.write({'accepted': True, 'amount': ev.get('amount') or 0.0})
                    continue
                vals.update(accepted=True, amount=ev.get('amount') or 0.0)
            self.create(vals)
        return True
