# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Cómo se nombra cada familia dentro del mensaje ("se te estaría terminando ...").
DEFAULT_LABELS = {
    'lavandina': 'la lavandina',
    'jabón para ropa': 'el jabón para la ropa',
    'suavizante': 'el suavizante',
    'detergente': 'el detergente',
    'limpiador desodorante': 'el limpiador desodorante',
    'desengrasante': 'el desengrasante',
    'cloro y químicos de pileta': 'el cloro de la pileta',
    'bolsas de residuo': 'las bolsas de residuo',
    'papel y rollos': 'el papel y los rollos de cocina',
    'perfume para ropa': 'el perfume para la ropa',
}


class CristalCfFamily(models.Model):
    _inherit = 'cristal.cf.family'

    wa_label = fields.Char(string='Cómo se nombra en el mensaje',
                           help='Ej.: "la lavandina". Va en "se te estaría terminando ...".')

    @api.model
    def _cristal_fid_set_default_labels(self):
        for family in self.search([('wa_label', '=', False)]):
            family.wa_label = DEFAULT_LABELS.get((family.name or '').strip().lower())
