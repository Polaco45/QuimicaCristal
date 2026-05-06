"""Migración post-update a 18.0.1.2.0.

v1.2.0 agrega:
- 2 campos nuevos en mcp.pending.message (notified_at, notification_skipped_reason)
- Cron 'MCP: Notificar a Joaco mensajes pendientes' (cada 5 min)
- Parámetros de configuración con valores por defecto

Los campos los crea Odoo automáticamente al actualizar el modelo.
Los registros del XML se cargan automáticamente con noupdate=1 (solo si no existen).
Por lo tanto esta migración no necesita hacer nada custom — solo log de éxito.
"""

import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    _logger.info(
        "MCP migration 18.0.1.2.0: v1.2 (notificación a Joaco) aplicada. "
        "Verificá los parámetros en Ajustes > Técnico > Parámetros del sistema "
        "(mcp_server.notify_*) y el cron 'MCP: Notificar a Joaco mensajes pendientes'."
    )
