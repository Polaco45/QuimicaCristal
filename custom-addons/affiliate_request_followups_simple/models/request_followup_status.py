from odoo import api, fields, models

class AffiliateRequest(models.Model):
    _inherit = 'affiliate.request'

    followup_stage = fields.Selection([
        ('requested', 'Solicitado'),
        ('to_approve', 'Pendiente de aprobación'),
        ('rejected', 'Rechazado'),
        ('approved', 'Aprobado'),
    ], string='Seguimiento', compute='_compute_followup_stage', store=True)

    @api.depends('state', 'write_date')  # <- NO 'id'
    def _compute_followup_stage(self):
        for rec in self:
            st = (rec.state or '').lower()
            rec.followup_stage = (
                'requested' if st in ('requested', 'draft', 'solicitado') else
                'to_approve' if st in ('pending', 'to_approve', 'pendiente') else
                'rejected' if st in ('rejected', 'cancel') else
                'approved' if st in ('approved', 'done', 'accepted') else
                'requested'
            )
