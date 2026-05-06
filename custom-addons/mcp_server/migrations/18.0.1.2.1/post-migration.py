"""Migración post-update a 18.0.1.2.1.

v1.2.1 — bugfix: el método de envío del cron de notificación buscaba
discuss.channel filtrando por whatsapp_account_id (campo inexistente).
Se corrigió buscando vía whatsapp.message en su lugar.

No requiere migración de datos. Solo log.
"""

import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    _logger.info(
        "MCP migration 18.0.1.2.1 aplicada: bugfix en cron de notificación. "
        "El cron ahora encuentra correctamente el canal vía whatsapp.message."
    )
