# -*- coding: utf-8 -*-
"""Tool: search_offers — busca ofertas vigentes."""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class SearchOffers(AgentTool):
    name = "search_offers"
    description = (
        "Busca ofertas activas y vigentes en cristal.agent.offer. Las ofertas las "
        "carga Joaco. Podés filtrar por nivel del cliente. Si only_proactive=True, "
        "solo trae las que están marcadas para comunicarse proactivamente "
        "(útil para cadencias salientes)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "level": {"type": "string", "enum": ["bronce", "plata", "oro"]},
            "only_proactive": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 10},
        },
    }

    def _execute(self, env, run=None, level=None, only_proactive=False, limit=10, **kwargs):
        results = env['cristal.agent.offer'].sudo().search_for_agent(
            level=level,
            only_proactive=bool(only_proactive),
            limit=int(limit or 10),
        )
        return {"ok": True, "count": len(results), "offers": results}
