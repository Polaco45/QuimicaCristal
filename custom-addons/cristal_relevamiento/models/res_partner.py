# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    relevamiento_ids = fields.One2many(
        'cristal.relevamiento', 'partner_id', string='Relevamientos')
    relevamiento_count = fields.Integer(
        string='Relevamientos', compute='_compute_relevamiento_count')

    def _compute_relevamiento_count(self):
        Rel = self.env['cristal.relevamiento']
        for partner in self:
            partner.relevamiento_count = Rel.search_count(
                [('partner_id', '=', partner.id)]) if partner.id else 0

    def action_open_relevamientos(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Relevamientos',
            'res_model': 'cristal.relevamiento',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }
