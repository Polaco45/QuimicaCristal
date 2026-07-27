# -*- coding: utf-8 -*-
"""Extiende mail.activity para las visitas de ruta (Piezas 5 y 6)."""
from odoo import api, fields, models

from .res_partner import RUTEO_VISIT_TYPES


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    ruteo_generated = fields.Boolean(
        string="Generada por ruteo", index=True, copy=False,
        help="Actividad de visita creada automáticamente por el generador de ruta diaria.")
    ruteo_sequence = fields.Integer(
        string="Orden en la ruta", copy=False,
        help="Posición del cliente en el recorrido del día (por cercanía).")
    ruteo_visit_type = fields.Selection(
        RUTEO_VISIT_TYPES, string="Tipo de visita", compute='_compute_ruteo_visit_type',
        help="Tipo de visita del cliente (para el badge de color en la ruta).")

    def _compute_ruteo_visit_type(self):
        Partner = self.env['res.partner']
        for act in self:
            if act.ruteo_generated and act.res_model == 'res.partner' and act.res_id:
                act.ruteo_visit_type = Partner.browse(act.res_id).ruteo_visit_type
            else:
                act.ruteo_visit_type = False

    def _ruteo_partner(self):
        self.ensure_one()
        if self.res_model == 'res.partner' and self.res_id:
            return self.env['res.partner'].browse(self.res_id)
        return self.env['res.partner']

    def action_ruteo_navigate(self):
        """Abre Google Maps para ir al cliente de esta visita."""
        self.ensure_one()
        partner = self._ruteo_partner()
        if partner:
            return partner.action_ruteo_open_maps()
        return False

    def action_ruteo_mark_visited(self):
        """Marca la visita como hecha (registra la última visita y cierra la actividad)."""
        self._action_done()
        return True

    def _action_done(self, feedback=False, attachment_ids=None):
        """Al cerrar una visita de ruta, registra la fecha de última visita en el
        cliente (para recalcular su próxima visita)."""
        ruteo_acts = self.filtered(
            lambda a: a.ruteo_generated and a.res_model == 'res.partner')
        partners = self.env['res.partner'].browse(ruteo_acts.mapped('res_id'))
        res = super()._action_done(feedback=feedback, attachment_ids=attachment_ids)
        if partners:
            partners._ruteo_register_visit()
        return res
