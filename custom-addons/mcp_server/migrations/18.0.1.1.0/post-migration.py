"""Migración post-update a 18.0.1.1.0.

Cuando se actualiza el módulo desde una versión anterior (18.0.1.0.0 o similar),
este script habilita los modelos y reportes nuevos del MCP usando upsert seguro
que NO falla si el usuario ya configuró manualmente alguno de ellos.
"""

import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Instalación nueva, post_init_hook se encarga
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    _logger.info("MCP migration 18.0.1.1.0: iniciando setup de modelos y reportes")

    try:
        from odoo.addons.mcp_server.models.mcp_setup import (
            setup_default_models, setup_default_reports,
        )
        models_result = setup_default_models(env)
        reports_result = setup_default_reports(env)
        _logger.info(
            "MCP migration 18.0.1.1.0: modelos=%s, reportes=%s",
            models_result, reports_result,
        )
    except Exception as e:
        _logger.exception(
            "MCP migration 18.0.1.1.0: error durante setup (no bloqueante): %s", e
        )
