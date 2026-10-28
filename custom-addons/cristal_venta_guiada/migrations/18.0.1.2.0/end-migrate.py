# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # El tamaño sugerido ahora es el más grande: recalcular sin esperar a la noche.
    api.Environment(cr, SUPERUSER_ID, {})['cristal.vg.suggestion']._cron_recompute()
