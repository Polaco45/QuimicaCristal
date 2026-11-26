# -*- coding: utf-8 -*-
"""Migración 18.0.1.82.6 — Los mensajes a clientes salen solo por su propio chat en una
cuenta de ventas (Sergio, 26/11/2026). Deja pedido el autotest, que incluye esos casos; lo
corre el cron de mantenimiento de Compras y guarda el resultado en la configuración."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if config:
        config.write({'purchase_selftest_log': 'pendiente'})
