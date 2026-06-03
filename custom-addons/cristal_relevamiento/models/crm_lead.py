# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # Relevamientos del cliente vinculado (colgados del partner, vistos desde el lead)
    relevamiento_ids = fields.One2many(
        related='partner_id.relevamiento_ids', readonly=False,
        string='Relevamientos del cliente')
    rel_stage_ok = fields.Boolean(
        string='Etapa habilita relevamiento', compute='_compute_rel_stage_ok')

    @api.depends('stage_id', 'stage_id.sequence')
    def _compute_rel_stage_ok(self):
        # "Relevamiento agendado" tiene sequence 3; de ahí en adelante se habilita.
        for lead in self:
            lead.rel_stage_ok = bool(lead.stage_id) and lead.stage_id.sequence >= 3
