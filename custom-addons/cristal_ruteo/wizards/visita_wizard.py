# -*- coding: utf-8 -*-
"""Asistente de cierre de visita: registrar (con nota) o posponer."""
from datetime import timedelta

from odoo import fields, models
from odoo.exceptions import UserError


class CristalVisitaWizard(models.TransientModel):
    _name = 'cristal.visita.wizard'
    _description = 'Registrar / posponer visita'

    partner_id = fields.Many2one('res.partner', string="Cliente", required=True)
    modo = fields.Selection([
        ('done', 'Visité'),
        ('posponer', 'Posponer'),
    ], required=True, default='done')
    note = fields.Text(
        string="¿Qué hiciste en la visita?",
        placeholder="Ej: dejé muestra de lavandina, interesado, cotizar pack cocina…")
    new_date = fields.Date(
        string="Nueva fecha",
        default=lambda self: fields.Date.context_today(self) + timedelta(days=1))
    reason = fields.Char(string="Motivo (opcional)")

    def action_confirm(self):
        self.ensure_one()
        if self.modo == 'done':
            self.partner_id._visit_register_done(note=self.note)
        else:
            if not self.new_date or self.new_date <= fields.Date.context_today(self):
                raise UserError("Elegí una fecha futura para posponer.")
            self.partner_id._visit_postpone(self.new_date, reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
