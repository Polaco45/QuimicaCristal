from odoo import models, fields

class AffiliateRequest(models.Model):
    _inherit = 'affiliate.request'

    # Etapa “tipo barra de estado”, mapeada al state existente
    followup_stage = fields.Selection([
        ('draft', 'Solicitado'),
        ('register', 'Pendiente de aprobación'),
        ('cancel', 'Rechazado'),
        ('approve', 'Aprobado'),
    ], compute='_compute_followup_stage', string='Etapa', store=False)

    def _compute_followup_stage(self):
        for rec in self:
            rec.followup_stage = rec.state or False
