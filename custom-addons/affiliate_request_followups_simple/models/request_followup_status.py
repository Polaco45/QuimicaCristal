# -*- coding: utf-8 -*-
from odoo import api, fields, models

class AffiliateRequest(models.Model):
    _inherit = "affiliate.request"

    # Timestamps de cada disparo de seguimiento
    followup_12h_at = fields.Datetime(string="Seguimiento 12h")
    followup_24h_at = fields.Datetime(string="Seguimiento 24h")
    followup_48h_at = fields.Datetime(string="Seguimiento 48h")

    # Etapa visible como statusbar
    followup_stage = fields.Selection([
        ("new", "Nuevo"),
        ("12h", "12 h"),
        ("24h", "24 h"),
        ("48h", "48 h"),
    ], string="Seguimiento", compute="_compute_followup_stage")

    def _compute_followup_stage(self):
        """Primero prioriza lo efectivamente ejecutado (campos *_at).
        Si aún no se ejecutó nada, calcula por antigüedad desde create_date.
        NOTA: sin @depends y store=False para que siempre se recalcule al abrir la vista.
        """
        now = fields.Datetime.now()
        for rec in self:
            stage = "new"
            if rec.followup_48h_at:
                stage = "48h"
            elif rec.followup_24h_at:
                stage = "24h"
            elif rec.followup_12h_at:
                stage = "12h"
            elif rec.create_date:
                elapsed = (now - rec.create_date).total_seconds() / 3600.0
                if elapsed >= 48:
                    stage = "48h"
                elif elapsed >= 24:
                    stage = "24h"
                elif elapsed >= 12:
                    stage = "12h"
            rec.followup_stage = stage
