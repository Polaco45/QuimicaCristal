# -*- coding: utf-8 -*-
"""Enganches de reparto sobre las transferencias (stock.picking)."""
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    reparto_id = fields.Many2one(
        'cristal.reparto', string="Vuelta de reparto", index=True, copy=False)
    reparto_sequence = fields.Integer(string="Orden de reparto", default=0, copy=False)
    reparto_notified = fields.Boolean(
        string="Avisado (próximo)", copy=False,
        help="Ya se le mandó el WhatsApp de 'sos el próximo' al cliente.")

    # ─────────── Disparadores ───────────
    def _action_done(self):
        res = super()._action_done()
        for picking in self:
            # Blindado: la lógica de reparto NUNCA debe romper la validación de
            # una transferencia. Corre con sudo (evita errores de permisos) y
            # tolera cualquier fallo.
            try:
                picking.sudo()._reparto_on_done()
            except Exception:  # noqa: BLE001
                _logger.exception("Reparto: fallo post-validación en %s", picking.name)
        return res

    def _reparto_on_done(self):
        self.ensure_one()
        pt = self.picking_type_id
        if pt.code == 'outgoing' and self.reparto_id:
            # Entrega hecha → avisar al próximo de la vuelta.
            self._reparto_notify_next()
        elif pt.warehouse_id and pt.warehouse_id.pack_type_id == pt:
            # PACK validada → sumar la entrega (OUT) a la vuelta del día.
            out = self._reparto_find_out()
            if out:
                self.env['cristal.reparto']._add_picking(out)

    def _reparto_find_out(self):
        """Desde una PACK, encuentra la orden de entrega (OUT) río abajo."""
        self.ensure_one()
        outs = self.move_ids.move_dest_ids.picking_id.filtered(
            lambda p: p.picking_type_id.code == 'outgoing'
            and p.state not in ('done', 'cancel'))
        return outs[:1]

    def _reparto_notify_next(self):
        """Al entregar esta OUT, avisa al próximo pendiente de la vuelta."""
        self.ensure_one()
        if not self.reparto_id:
            return
        nxt = self.reparto_id._next_pending(self.reparto_sequence)
        if nxt and not nxt.reparto_notified:
            nxt._reparto_send_next_whatsapp()
            nxt.reparto_notified = True

    def _reparto_send_next_whatsapp(self):
        """Envía el aviso de 'sos el próximo'. (Pieza B: envío real por plantilla.)"""
        self.ensure_one()
        _logger.info(
            "📲 Reparto (stub): avisar al próximo → %s (%s)",
            self.partner_id.name,
            self.partner_id.mobile or self.partner_id.phone or 'sin teléfono')

    # ─────────── Acción del repartidor ───────────
    def action_reparto_delivered(self):
        """Marca la entrega como hecha (valida la transferencia)."""
        self.ensure_one()
        return self.button_validate()
