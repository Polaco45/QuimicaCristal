from . import models
from . import controllers


def post_init_hook(env):
    """Setup post-instalación: habilita modelos comunes para el MCP usando upsert.

    No falla si los registros ya existen (respeta configuración previa del usuario).
    """
    from .models.mcp_setup import setup_default_models, setup_default_reports
    setup_default_models(env)
    setup_default_reports(env)
