# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api

from odoo.addons.cristal_venta_guiada import setup_checkout_promo


def migrate(cr, version):
    setup_checkout_promo(api.Environment(cr, SUPERUSER_ID, {}))
