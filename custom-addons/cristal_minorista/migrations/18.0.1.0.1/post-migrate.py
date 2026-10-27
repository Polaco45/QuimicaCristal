# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Recalcular el tipo de cliente con la regla nueva (palabras del nombre)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    partners = env['res.partner'].with_context(active_test=False).search([])
    env.add_to_compute(partners._fields['cristal_customer_type'], partners)
    env.flush_all()
