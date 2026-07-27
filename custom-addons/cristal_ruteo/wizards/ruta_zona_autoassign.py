# -*- coding: utf-8 -*-
"""Asistente para armar las zonas de ruteo automáticamente por cercanía."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RutaZonaAutoassign(models.TransientModel):
    _name = 'cristal.ruta.zona.autoassign'
    _description = 'Armar zonas de ruteo automáticamente'

    user_id = fields.Many2one(
        'res.users', string="Vendedor", required=True,
        help="Se agruparán los clientes de la cartera de este vendedor.")
    n_zonas = fields.Integer(
        string="Cantidad de zonas", default=5, required=True,
        help="Normalmente una por día hábil (5 = Lunes a Viernes).")
    reset_existing = fields.Boolean(
        string="Reemplazar zonas actuales", default=True,
        help="Borra las zonas previas del vendedor y las rehace desde cero.")
    located_count = fields.Integer(
        string="Clientes geolocalizados", compute='_compute_located_count')

    @api.depends('user_id')
    def _compute_located_count(self):
        Partner = self.env['res.partner']
        for wiz in self:
            wiz.located_count = Partner.search_count([
                ('user_id', '=', wiz.user_id.id),
                ('ruteo_is_located', '=', True),
            ]) if wiz.user_id else 0

    def action_confirm(self):
        self.ensure_one()
        if not 1 <= self.n_zonas <= 6:
            raise UserError(_("Elegí entre 1 y 6 zonas (una por día hábil)."))
        zonas = self.env['cristal.ruta.zona'].autoassign_zonas(
            self.user_id.id, n_zonas=self.n_zonas, reset=self.reset_existing)
        return {
            'type': 'ir.actions.act_window',
            'name': _("Zonas de %s") % self.user_id.name,
            'res_model': 'cristal.ruta.zona',
            'view_mode': 'list,form',
            'domain': [('id', 'in', zonas.ids)],
        }
