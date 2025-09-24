# -*- coding: utf-8 -*-
{
    "name": "Affiliate Request Followups (Simple)",
    "summary": "Recordatorios 12/24/48h para solicitudes de afiliación, con dedupe por email e idempotencia por etapa.",
    "version": "18.0.1.0.0",
    "author": "Tu Equipo",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "affiliate_management",  # módulo que define affiliate.request
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/cron.xml",
        "views/request_followup_status.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "affiliate_request_followups_simple/static/src/scss/statusbar.scss",
        ],
    },
    "installable": True,
    "application": False,
}
