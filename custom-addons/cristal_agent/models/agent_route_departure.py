# -*- coding: utf-8 -*-
"""
Salidas de la ruta del camión — un registro por jueves de cada circuito.

Las salidas NO se calculan al vuelo: se generan como registros (`generate_upcoming`)
para poder darles estado (preventa / rescate / confirmada / postergada / realizada),
postergarlas (cambiar la fecha), activar el Plan B (rescate: envío gratis desde
$75.000 + producto de cortesía) y acumular el monto de preventa.
"""
import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

DEFAULT_TZ = 'America/Argentina/Cordoba'


class CristalAgentRouteDeparture(models.Model):
    _name = 'cristal.agent.route.departure'
    _description = 'Salida de la ruta del camión'
    _order = 'date, circuit_id'

    name = fields.Char(compute='_compute_name', store=True)
    circuit_id = fields.Many2one(
        'cristal.agent.circuit', required=True, ondelete='cascade', index=True)
    date = fields.Date(string="Fecha de salida (jueves)", required=True, index=True)
    state = fields.Selection([
        ('preventa', 'Preventa'),
        ('rescate', 'Rescate (Plan B)'),
        ('confirmada', 'Confirmada'),
        ('postergada', 'Postergada'),
        ('realizada', 'Realizada'),
    ], default='preventa', required=True, index=True)
    rescue_free_shipping_from = fields.Float(
        string="Envío gratis desde (rescate)", default=75000.0,
        help="Cuando la salida está en rescate, el envío es gratis desde este monto.")
    courtesy_product_id = fields.Many2one(
        'product.product', string="Producto de cortesía (rescate)",
        help="Producto que el bot ofrece como cortesía cuando la salida está en rescate.")
    preventa_amount = fields.Float(
        string="Monto de preventa", compute='_compute_preventa_amount',
        help="Suma de subtotales de productos (sin IVA ni flete) de las órdenes de esta salida.")
    order_ids = fields.One2many(
        'sale.order', 'route_departure_id', string="Órdenes")

    _sql_constraints = [
        ('circuit_date_uniq', 'unique(circuit_id, date)',
         'Ya existe una salida para ese circuito y esa fecha.'),
    ]

    @api.depends('circuit_id', 'date')
    def _compute_name(self):
        for dep in self:
            c = dep.circuit_id.name or 'Circuito'
            dep.name = f"{c} — {dep.date}" if dep.date else c

    @api.depends('order_ids.order_line.price_subtotal',
                 'order_ids.order_line.product_id')
    def _compute_preventa_amount(self):
        config = self.env['cristal.agent.config'].sudo().get_active()
        freight_id = config.route_freight_product_id.id if (
            config and config.route_freight_product_id) else False
        for dep in self:
            total = 0.0
            for order in dep.order_ids:
                for line in order.order_line:
                    if freight_id and line.product_id.id == freight_id:
                        continue
                    total += line.price_subtotal
            dep.preventa_amount = total

    def get_preventa_cutoff(self):
        """Cierre de preventa: el martes (config) 18:00 hora Córdoba previo a la
        salida, devuelto como datetime naive en UTC (como guarda Odoo)."""
        self.ensure_one()
        config = self.env['cristal.agent.config'].sudo().get_active()
        cutoff_weekday = int(getattr(config, 'route_preventa_cutoff_weekday', 1) or 1)
        cutoff_hour = float(getattr(config, 'route_preventa_cutoff_hour', 18.0) or 18.0)
        tzname = (config.timezone if config and config.timezone else DEFAULT_TZ)
        tz = pytz.timezone(tzname)
        # Retroceder desde la fecha de salida hasta el weekday de cierre.
        d = self.date
        for _ in range(7):
            if d.weekday() == cutoff_weekday and d < self.date:
                break
            d = d - timedelta(days=1)
        hour = int(cutoff_hour)
        minute = int(round((cutoff_hour - hour) * 60))
        local_dt = tz.localize(datetime.combine(d, time(hour, minute)))
        return local_dt.astimezone(pytz.utc).replace(tzinfo=None)

    def get_commitment_datetime(self):
        """Fecha/hora de entrega comprometida: el jueves de la salida a las 09:00
        hora Córdoba (entregas por la mañana), en UTC naive."""
        self.ensure_one()
        config = self.env['cristal.agent.config'].sudo().get_active()
        tzname = (config.timezone if config and config.timezone else DEFAULT_TZ)
        tz = pytz.timezone(tzname)
        local_dt = tz.localize(datetime.combine(self.date, time(9, 0)))
        return local_dt.astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def generate_upcoming(self, weeks=12):
        """Genera las salidas de las próximas `weeks` semanas por rotación de 28
        días desde first_departure_date de cada circuito. Idempotente: no duplica
        (circuit_id, date). Devuelve la cantidad creada."""
        Circuit = self.env['cristal.agent.circuit'].sudo()
        today = fields.Date.context_today(self)
        horizon = today + timedelta(weeks=weeks)
        created = 0
        for circuit in Circuit.search([('active', '=', True)]):
            if not circuit.first_departure_date:
                continue
            d = circuit.first_departure_date
            # Avanzar hasta la primera fecha >= hoy (por si first_departure ya pasó).
            while d < today:
                d = d + timedelta(days=28)
            while d <= horizon:
                exists = self.search_count([
                    ('circuit_id', '=', circuit.id), ('date', '=', d)])
                if not exists:
                    self.create({'circuit_id': circuit.id, 'date': d,
                                 'state': 'preventa'})
                    created += 1
                d = d + timedelta(days=28)
        _logger.info("generate_upcoming: %s salidas creadas (horizonte %s semanas).",
                     created, weeks)
        return created
