# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    cristal_has_afip_responsibility = fields.Boolean(
        string='Tiene responsabilidad AFIP', compute='_compute_cristal_has_afip_responsibility')

    @api.depends('commercial_partner_id.l10n_ar_afip_responsibility_type_id')
    def _compute_cristal_has_afip_responsibility(self):
        for partner in self:
            partner.cristal_has_afip_responsibility = bool(
                partner.commercial_partner_id.l10n_ar_afip_responsibility_type_id)

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        if fields_list:
            fields_list.append('cristal_has_afip_responsibility')
        return fields_list
