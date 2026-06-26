# -*- coding: utf-8 -*-
"""
Migración 18.0.1.17.0 — Arregla el seguimiento de cotizaciones + dispara el backlog.

- FIX: send_whatsapp_template ahora busca el template por `name` O `template_name`
  (antes solo por `name`, y el bot pasaba el técnico 'hola_mayorista_crm' → "no
  existe" → escalaba en vez de mandar).
- El cron de seguimiento ahora tiene CATCH-UP: las cotizaciones que nunca tuvieron
  seguimiento (last_cadence_step_executed < 0) reciben UN toque, aunque estén fuera
  de los días [1,3,7].
- Esta migración resetea el contador de las cotizaciones en cola (phase_2_quoted)
  a -1, para que en la próxima corrida del cron se disparen TODAS (ejecutar
  pendientes), ahora que el template funciona.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    leads = env['crm.lead'].search([
        ('agent_strategy_phase', '=', 'phase_2_quoted'),
        ('active', '=', True),
    ])
    partners = leads.mapped('partner_id')
    if not partners:
        _logger.info("MIGRATION 1.17.0: no hay cotizaciones en cola")
        return

    mems = env['cristal.agent.memory'].search([('partner_id', 'in', partners.ids)])
    if mems:
        mems.write({'last_cadence_step_executed': -1})
        _logger.info(
            "✅ MIGRATION 1.17.0: %s cotizaciones marcadas para seguimiento "
            "(catch-up en la próxima corrida del cron)", len(mems))
