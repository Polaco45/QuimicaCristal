# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api

from odoo.addons.cristal_venta_guiada import COMBOS_1L, _combos_category, _create_combo


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    category = _combos_category(env)
    for name, price, slots in COMBOS_1L:
        _create_combo(env, name, price, slots, category)
