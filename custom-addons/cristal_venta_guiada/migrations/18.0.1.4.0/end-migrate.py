# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # La web con la escalera de la caja desde ya, sin esperar al recálculo nocturno.
    api.Environment(cr, SUPERUSER_ID, {})['cristal.vg.suggestion']._cristal_sync_website()
