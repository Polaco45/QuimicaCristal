from odoo import api, fields, models

class AffiliateRequest(models.Model):
    _inherit = 'affiliate.request'

    # Etapa mostrada como statusbar
    followup_progress = fields.Selection(
        [
            ('none', 'Sin recordatorio'),
            ('h12', '12 h enviado'),
            ('h24', '24 h enviado'),
            ('h48', '48 h enviado'),
        ],
        string='Progreso de recordatorios',
        compute='_compute_followup_progress',
        store=False,  # on-the-fly, así no indexa ni rompe nada
    )

    # Info útil en la vista
    last_followup_date = fields.Datetime(
        string='Último recordatorio',
        compute='_compute_last_followup_date',
        store=False,
    )

    @api.depends('id')
    def _compute_followup_progress(self):
        Log = self.env['affiliate.request.followup.log']
        for rec in self:
            # Contamos logs de seguimiento de esta solicitud.
            # Si tenés un campo "kind" o "step", podés filtrar más,
            # p.ej. [('kind', '=', 'reminder')]
            count = Log.search_count([('request_id', '=', rec.id)])

            if count >= 3:
                rec.followup_progress = 'h48'
            elif count == 2:
                rec.followup_progress = 'h24'
            elif count == 1:
                rec.followup_progress = 'h12'
            else:
                rec.followup_progress = 'none'

    def _compute_last_followup_date(self):
        Log = self.env['affiliate.request.followup.log']
        for rec in self:
            log = Log.search([('request_id', '=', rec.id)],
                             order='create_date desc', limit=1)
            rec.last_followup_date = log.create_date if log else False
