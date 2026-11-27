# -*- coding: utf-8 -*-
"""v1.83.2 — Borradores de empresas: pide el autotest tras la actualización."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([], limit=1)
    if config:
        config.write({'client_draft_selftest_log': 'pendiente'})
