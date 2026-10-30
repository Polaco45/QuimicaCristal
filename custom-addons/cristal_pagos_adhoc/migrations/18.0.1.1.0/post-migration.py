from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    from odoo.addons.cristal_pagos_adhoc.hooks import translate_receipt_report

    translate_receipt_report(api.Environment(cr, SUPERUSER_ID, {}))
