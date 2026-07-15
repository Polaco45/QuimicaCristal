# -*- coding: utf-8 -*-
"""Registro auditado de cada acción de cobranza ejecutada."""
from odoo import models, fields, api

from .res_partner import STAGE_SELECTION


class CristalCobranzaAction(models.Model):
    _name = 'cristal.cobranza.action'
    _description = "Cristal Cobranza — Acción ejecutada"
    _order = 'action_datetime desc, id desc'

    partner_id = fields.Many2one(
        'res.partner', string="Cliente", required=True,
        ondelete='cascade', index=True)
    action_datetime = fields.Datetime(
        string="Fecha/hora", default=fields.Datetime.now, index=True)
    stage = fields.Selection(STAGE_SELECTION, string="Nivel", required=True)
    channel = fields.Selection([
        ('whatsapp', 'WhatsApp'),
        ('email', 'Email'),
        ('activity', 'Actividad'),
    ], string="Canal", required=True)
    state = fields.Selection([
        ('sent', 'Enviado / creado'),
        ('failed', 'Error'),
        ('skipped', 'Salteado'),
    ], string="Resultado", default='sent', index=True)

    total_vencido = fields.Float(string="Total vencido")
    amount_display = fields.Char(string="Importe")
    cant_vencidas = fields.Integer(string="Facturas vencidas")
    dias_mora_max = fields.Integer(string="Días de mora (máx.)")

    wa_message_id = fields.Many2one('whatsapp.message', string="Mensaje WhatsApp")
    activity_id = fields.Many2one('mail.activity', string="Actividad")
    attachment_id = fields.Many2one('ir.attachment', string="PDF enviado")
    run_id = fields.Many2one('cristal.agent.run', string="Run del agente")
    note = fields.Text(string="Detalle")

    @api.depends('partner_id', 'stage')
    def _compute_display_name(self):
        labels = dict(STAGE_SELECTION)
        for rec in self:
            rec.display_name = "%s — %s" % (
                rec.partner_id.display_name or '?',
                labels.get(rec.stage, rec.stage or ''))
