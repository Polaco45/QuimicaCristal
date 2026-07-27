# -*- coding: utf-8 -*-
"""Extiende mail.activity para las visitas de ruta (Piezas 5 y 6)."""
from odoo import fields, models


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    ruteo_generated = fields.Boolean(
        string="Generada por ruteo", index=True, copy=False,
        help="Actividad de visita creada automáticamente por el generador de ruta diaria.")
    ruteo_sequence = fields.Integer(
        string="Orden en la ruta", copy=False,
        help="Posición del cliente en el recorrido del día (por cercanía).")

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
