import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Recalcula el diario actual de los cheques que quedaron sin él (484 a 486)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Check = env["l10n_latam.check"]
    checks = Check.search([("current_journal_id", "=", False), ("payment_id", "!=", False)])
    if not checks:
        return
    env.add_to_compute(Check._fields["current_journal_id"], checks)
    checks.flush_recordset(["current_journal_id"])
    fixed = checks.filtered("current_journal_id")
    _logger.info(
        "cristal_pagos_adhoc 18.0.1.3.0: diario actual recalculado en %s cheques (%s con diario): %s",
        len(checks), len(fixed), fixed.mapped("name"),
    )
