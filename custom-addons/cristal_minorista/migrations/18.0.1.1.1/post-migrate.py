# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # Celulares escritos con el 9 y el 15 a la vez ahora tienen clave de WhatsApp.
    env = api.Environment(cr, SUPERUSER_ID, {})
    partners = env['res.partner'].with_context(active_test=False).search([
        ('cristal_wa_key', '=', False), '|', ('mobile', '!=', False), ('phone', '!=', False)])
    env.add_to_compute(partners._fields['cristal_wa_key'], partners)
    env.flush_all()
