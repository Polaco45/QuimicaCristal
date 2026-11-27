# -*- coding: utf-8 -*-
"""v1.83.1 — Borradores de empresas: carga el conocimiento del rubro de arranque (si está
vacío) para que quede a la vista y editable en la configuración, y pide el autotest."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([], limit=1)
    if not config:
        return
    from odoo.addons.cristal_agent.services.client_consult import DEFAULT_KNOWLEDGE
    vals = {'client_draft_selftest_log': 'pendiente'}
    if not (config.client_draft_knowledge or '').strip():
        vals['client_draft_knowledge'] = DEFAULT_KNOWLEDGE
    config.write(vals)
