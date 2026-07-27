# -*- coding: utf-8 -*-
"""Asistente para posponer (reprogramar) una visita a otra fecha."""
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class RutaVisitaPostpone(models.TransientModel):
    _name = 'cristal.ruta.visita.postpone'
    _description = 'Posponer visita de ruta'

    visita_id = fields.Many2one('cristal.ruta.visita', string="Visita", required=True)
    partner_id = fields.Many2one(related='visita_id.partner_id', string="Cliente")
    new_date = fields.Date(
        string="Nueva fecha", required=True,
        default=lambda self: fields.Date.context_today(self) + timedelta(days=1))
    reason = fields.Char(string="Motivo (opcional)")

    def action_confirm(self):
        self.ensure_one()
        visita = self.visita_id
        if self.new_date <= visita.visit_date:
            raise UserError("La nueva fecha tiene que ser posterior a la de hoy.")
        # La visita original queda como 'pospuesta' (historial para el control)…
        visita.write({
            'state': 'pospuesta',
            'postponed_to': self.new_date,
            'notes': ((visita.notes or '') + ("\nPospuesta: %s" % self.reason if self.reason else "")).strip() or False,
        })
        # …y se crea una nueva visita pendiente en la fecha elegida.
        nueva = visita.copy({
            'visit_date': self.new_date,
            'state': 'pendiente',
            'postponed_to': False,
            'visited_at': False,
            'outcome': False,
        })
        body = "Visita pospuesta del %s al %s" % (
            fields.Date.to_string(visita.visit_date), fields.Date.to_string(self.new_date))
        if self.reason:
            body += " — %s" % self.reason
        (visita.lead_id or visita.partner_id).message_post(body=body)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'cristal.ruta.visita',
            'res_id': nueva.id,
            'view_mode': 'form',
        }
