"""Migración post-update a 18.0.1.3.0.

v1.3 agrega:
- Tool view_attachment para procesamiento multimodal de imágenes.
- Bugfix en filtro de ruido (_classify_noise): ahora cubre respuestas
  manuales nuestras, no solo templates automáticos.
- Heurística "pregunta pendiente": si nuestro último outbound contenía
  signo de interrogación, la respuesta corta del cliente se considera
  CONFIRMACIÓN legítima y NO se filtra como ruido.

No requiere cambios de datos.
"""

import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    _logger.info(
        "MCP migration 18.0.1.3.0 aplicada: tool view_attachment + "
        "filtro de ruido reforzado."
    )
