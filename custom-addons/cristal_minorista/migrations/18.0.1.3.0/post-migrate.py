# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields


def migrate(cr, version):
    """Clientes etiquetados Mayorista o que compran a precio mayorista dejan de figurar como
    consumidor final (29/10/2026: 868 con etiqueta y 129 con pedidos mayoristas estaban como CF)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['cristal.minorista.engine']._refresh_wholesale_buyers(fields.Datetime.now() - timedelta(days=730))
    partners = env['res.partner'].with_context(active_test=False).search([])
    env.add_to_compute(partners._fields['cristal_customer_type'], partners)
    env.flush_all()
