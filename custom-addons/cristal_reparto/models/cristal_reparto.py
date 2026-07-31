# -*- coding: utf-8 -*-
"""
Vuelta de reparto del día.

Agrupa las entregas (SM/OUT) en una lista ordenada por cercanía desde el local.
El repartidor la reordena antes de salir; al marcar entregado cada pedido, al
próximo de la lista le llega el aviso de WhatsApp (Pieza B).
"""
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Local de Química Cristal — Av. San Martín 2350, Río Cuarto (georef).
DEPOT_LAT = -33.1159928
DEPOT_LNG = -64.3788190


class CristalReparto(models.Model):
    _name = 'cristal.reparto'
    _description = 'Vuelta de reparto'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string="Vuelta", compute='_compute_name', store=True)
    date = fields.Date(string="Fecha", required=True, index=True,
                       default=fields.Date.context_today, tracking=True)
    driver_id = fields.Many2one('res.users', string="Repartidor", tracking=True)
    state = fields.Selection([
        ('draft', 'Preparando'),
        ('en_ruta', 'En ruta'),
        ('finalizada', 'Finalizada'),
    ], string="Estado", default='draft', required=True, index=True, tracking=True)

    picking_ids = fields.One2many('stock.picking', 'reparto_id', string="Entregas")
    total_count = fields.Integer(compute='_compute_counts', store=True)
    delivered_count = fields.Integer(compute='_compute_counts', store=True)
    pending_count = fields.Integer(compute='_compute_counts', store=True)
    progress = fields.Float(string="Avance", compute='_compute_counts', store=True)
    last_delivered_id = fields.Many2one(
        'stock.picking', string="Última entrega", compute='_compute_counts', store=True)
    next_pending_id = fields.Many2one(
        'stock.picking', string="Próxima entrega", compute='_compute_counts', store=True)

    @api.depends('date')
    def _compute_name(self):
        for run in self:
            run.name = "Reparto %s" % (fields.Date.to_string(run.date) or '')

    @api.depends('picking_ids.state', 'picking_ids.reparto_sequence')
    def _compute_counts(self):
        for run in self:
            pickings = run.picking_ids.filtered(lambda p: p.state != 'cancel')
            delivered = pickings.filtered(lambda p: p.state == 'done')
            pending = (pickings - delivered).sorted('reparto_sequence')
            run.total_count = len(pickings)
            run.delivered_count = len(delivered)
            run.pending_count = len(pending)
            run.progress = (100.0 * len(delivered) / len(pickings)) if pickings else 0.0
            run.last_delivered_id = delivered.sorted('reparto_sequence')[-1:].id
            run.next_pending_id = pending[:1].id

    # ─────────── Alta de entregas ───────────
    @api.model
    def _get_or_create_today(self):
        """Devuelve la vuelta abierta de hoy (o la crea)."""
        today = fields.Date.context_today(self)
        run = self.search([('date', '=', today), ('state', '!=', 'finalizada')],
                          order='id desc', limit=1)
        if not run:
            run = self.create({'date': today})
        return run

    @api.model
    def _add_picking(self, picking):
        """Suma una entrega (OUT) a la vuelta de hoy si no está ya en una."""
        picking.ensure_one()
        if picking.reparto_id or picking.state == 'cancel':
            return picking.reparto_id
        run = self._get_or_create_today()
        next_seq = max(run.picking_ids.mapped('reparto_sequence') or [0]) + 10
        picking.write({'reparto_id': run.id, 'reparto_sequence': next_seq})
        _logger.info("🚚 Reparto: %s sumada a %s (orden %s)",
                     picking.name, run.name, next_seq)
        return run

    def _next_pending(self, after_seq):
        """La próxima entrega pendiente después de una posición dada."""
        self.ensure_one()
        candidates = self.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel')
            and p.reparto_sequence > after_seq
        ).sorted('reparto_sequence')
        return candidates[:1]

    # ─────────── Acciones ───────────
    @api.model
    def action_open_today(self):
        """Abre (o crea) la vuelta de reparto de hoy."""
        run = self._get_or_create_today()
        return {
            'type': 'ir.actions.act_window',
            'name': run.name,
            'res_model': 'cristal.reparto',
            'res_id': run.id,
            'view_mode': 'form',
        }

    def action_start(self):
        for run in self:
            run.state = 'en_ruta'
        return True

    def action_finish(self):
        for run in self:
            run.state = 'finalizada'
        return True

    def action_reset_draft(self):
        for run in self:
            run.state = 'draft'
        return True

    def action_optimize_order(self):
        """Reordena las entregas pendientes por cercanía desde el local (vecino
        más cercano). Geolocaliza primero las que falten (best-effort)."""
        self.ensure_one()
        Partner = self.env['res.partner']
        pending = self.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
        # Geolocalizar las que tengan dirección y no estén ubicadas.
        to_geo = pending.mapped('partner_id').filtered(
            lambda pt: not pt.ruteo_is_located and pt._ruteo_has_geocodable_address())
        if to_geo:
            to_geo._ruteo_geolocalize_batch(throttle=True)

        located = pending.filtered(lambda p: p.partner_id.ruteo_is_located)
        sin_ubicar = pending - located
        pts = [(p.id, p.partner_id.partner_latitude, p.partner_id.partner_longitude)
               for p in located]
        ordered = self.env['cristal.ruta.zona']._nearest_neighbor_order(
            pts, (DEPOT_LAT, DEPOT_LNG))
        seq = 10
        for pid, _lat, _lng in ordered:
            self.env['stock.picking'].browse(pid).reparto_sequence = seq
            seq += 10
        # Las sin ubicar van al final, respetando su orden actual.
        for picking in sin_ubicar.sorted('reparto_sequence'):
            picking.reparto_sequence = seq
            seq += 10
        return True
