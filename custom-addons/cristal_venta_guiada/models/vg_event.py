# -*- coding: utf-8 -*-
import json
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


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
        ('checkout', 'Promo de caja'),
        ('qty', 'Llevando N'),
    ], string='Tipo')
    accepted = fields.Boolean(string='Aceptada')
    amount = fields.Float(string='Monto sumado')
    channel = fields.Selection([('pos', 'Caja'), ('web', 'Web')], string='Canal', default='pos', index=True)

    # Orden por defecto de la escalera (Joaco, 28/10/2026: de mayor a menor).
    LADDER_DEFAULT = ['combo', 'qty', 'size', 'other']
    LADDER_PARAM = 'cristal_venta_guiada.ladder_order'
    LADDER_MIN_OFFERS = 30

    @api.model
    def _ladder_group(self, kind):
        return kind if kind in ('combo', 'qty', 'size') else 'other'

    @api.model
    def _ladder_stats(self, channel, days=30):
        """{grupo: (ofertas, aceptadas)} de los últimos días en ese canal. La promo de
        caja no entra: siempre va al final, a todos."""
        since = fields.Datetime.now() - timedelta(days=days)
        stats = {g: [0, 0] for g in self.LADDER_DEFAULT}
        for row in self.read_group(
                [('channel', '=', channel), ('date', '>=', since), ('kind', '!=', 'checkout'), ('kind', '!=', False)],
                ['kind', 'accepted'], ['kind', 'accepted'], lazy=False):
            g = self._ladder_group(row['kind'])
            stats[g][0] += row['__count']
            if row['accepted']:
                stats[g][1] += row['__count']
        return {g: tuple(v) for g, v in stats.items()}

    @api.model
    def _ladder_order(self, channel, days=30):
        """La escalera se reordena sola: el escalón que más aceptan va primero. Un
        grupo recién cuenta con LADDER_MIN_OFFERS ofertas; hasta entonces conserva
        su lugar por defecto (detrás de los que ya tienen datos)."""
        stats = self._ladder_stats(channel, days)

        def key(group):
            offers, accepted = stats[group]
            rate = accepted / offers if offers >= self.LADDER_MIN_OFFERS else -1.0
            return (-rate, self.LADDER_DEFAULT.index(group))
        return sorted(self.LADDER_DEFAULT, key=key)

    @api.model
    def _ladder_orders(self):
        """Orden vigente por canal, guardado por el recálculo nocturno."""
        raw = self.env['ir.config_parameter'].sudo().get_param(self.LADDER_PARAM)
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        return {ch: data.get(ch) or self.LADDER_DEFAULT for ch in ('pos', 'web')}

    @api.model
    def _cron_update_ladder_order(self):
        before = self._ladder_orders()
        after = {ch: self._ladder_order(ch) for ch in ('pos', 'web')}
        self.env['ir.config_parameter'].sudo().set_param(self.LADDER_PARAM, json.dumps(after))
        for ch in after:
            if after[ch] != before[ch]:
                _logger.info("venta guiada: la escalera %s cambia de %s a %s", ch, before[ch], after[ch])
        return after

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
                'channel': ev.get('channel') or 'pos',
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
