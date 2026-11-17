from odoo import fields, models

from .res_partner import INST_STAGES


class CristalInstStageLog(models.Model):
    _name = 'cristal.inst.stage.log'
    _description = 'Institucional: cambio de etapa'
    _order = 'date desc, id desc'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one('res.partner', 'Empresa', required=True, index=True, ondelete='cascade')
    date = fields.Date('Fecha', required=True, index=True, default=fields.Date.context_today)
    stage_from = fields.Selection(INST_STAGES, 'Venía de')
    stage_to = fields.Selection(INST_STAGES, 'Pasó a', required=True)
    days_in_previous = fields.Integer('Días en la etapa anterior', aggregator='avg')


class CristalInstSnapshot(models.Model):
    _name = 'cristal.inst.snapshot'
    _description = 'Institucional: foto semanal del embudo'
    _order = 'date desc, stage'

    date = fields.Date('Semana', required=True, index=True)
    stage = fields.Selection(INST_STAGES, 'Etapa', required=True)
    count = fields.Integer('Empresas')
    at_risk = fields.Integer('En riesgo')
    dormant = fields.Integer('Dormidas')
    overdue = fields.Integer('Fecha límite vencida')
    margin_month = fields.Float('Margen por mes')
