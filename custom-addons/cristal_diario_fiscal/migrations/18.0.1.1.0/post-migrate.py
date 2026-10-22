# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api

from odoo.addons.cristal_diario_fiscal import setup_cristal_fiscal


def migrate(cr, version):
    setup_cristal_fiscal(api.Environment(cr, SUPERUSER_ID, {}))
