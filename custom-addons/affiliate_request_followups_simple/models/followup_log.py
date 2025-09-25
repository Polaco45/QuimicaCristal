# -*- coding: utf-8 -*-
from odoo import api, fields, models

class AffiliateRequestFollowupLog(models.Model):
    _name = "affiliate.request.followup.log"
    _description = "Followup log por etapa para affiliate.request"
    _order = "id desc"

    request_id = fields.Many2one(
        "affiliate.request",
        string="Solicitud",
        required=True,
        index=True,
        ondelete="cascade",
    )
    stage = fields.Selection(
        selection=[("12", "12h"), ("24", "24h"), ("48", "48h")],
        string="Etapa",
        required=True,
        index=True,
    )

    _sql_constraints = [
        (
            "uniq_request_stage",
            "unique(request_id, stage)",
            "Ya existe un envío para esta solicitud y etapa.",
        )
    ]
