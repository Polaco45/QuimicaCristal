# -*- coding: utf-8 -*-
"""Migración 18.0.1.78.0 — Compras en modo consulta, completo:

- Plantilla de utilidad para avisarle a Sergio con la ventana de 24 h cerrada (queda en
  borrador; el cron la manda a aprobar a Meta solo en producción).
- Deja pedido el autotest: lo corre el cron de mantenimiento con todos los módulos ya
  cargados y guarda el resultado en la configuración.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        return
    try:
        with cr.savepoint():
            from odoo.addons.cristal_agent.services import purchase_consult as pc
            pc.ensure_purchase_template(env, config.purchase_wa_account_id)
    except Exception as e:  # noqa: BLE001
        _logger.warning("Compras: no pude crear la plantilla de aviso: %s", e)
    config.write({'purchase_selftest_log': 'pendiente'})
