import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Devuelve a su diario los cheques en cartera que quedaron sin él (484 a 486).

    Solo los que nunca se movieron (sin operaciones posteriores): recalcular los demás
    podría cambiar el diario de cheques ya depositados o entregados.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Check = env["l10n_latam.check"]
    checks = Check.search([
        ("current_journal_id", "=", False),
        ("payment_id.state", "not in", ["draft", "canceled"]),
        ("payment_id.payment_type", "=", "inbound"),
    ]).filtered(lambda c: not c.operation_ids.filtered(lambda p: p.state not in ["draft", "canceled"]))
    if not checks:
        return
    env.add_to_compute(Check._fields["current_journal_id"], checks)
    checks.flush_recordset(["current_journal_id"])
    fixed = checks.filtered("current_journal_id")
    _logger.info(
        "cristal_pagos_adhoc 18.0.1.3.1: diario actual recalculado en %s cheques (%s con diario): %s",
        len(checks), len(fixed), fixed.mapped("name"),
    )
