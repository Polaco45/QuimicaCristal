# -*- coding: utf-8 -*-
"""Tool: search_knowledge — busca en la base de conocimiento."""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class SearchKnowledge(AgentTool):
    name = "search_knowledge"
    description = (
        "Busca en la base de conocimiento (cristal.agent.knowledge) entries activas "
        "y vigentes. La KB tiene políticas comerciales, FAQs, ofertas, observaciones "
        "globales, eventos, etc. Categorías: precio, politica_comercial, oferta_activa, "
        "producto, regla_negocio, observacion_cliente, faq, evento, estrategia_marketing, otro. "
        "El system prompt ya recibe la KB filtrada para el cliente actual, pero podés usar "
        "este tool si necesitás más entries específicas."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Filtrar por categoría (opcional).",
            },
            "partner_id": {
                "type": "integer",
                "description": "Filtrar entries aplicables a un partner específico (opcional).",
            },
            "level": {
                "type": "string",
                "enum": ["bronce", "plata", "oro"],
                "description": "Filtrar por nivel del cliente (opcional).",
            },
            "limit": {
                "type": "integer",
                "default": 20,
            },
        },
    }

    def _execute(self, env, run=None, category=None, partner_id=None,
                 level=None, limit=20, **kwargs):
        Knowledge = env['cristal.agent.knowledge'].sudo()
        results = Knowledge.search_for_agent(
            category=category,
            partner_id=int(partner_id) if partner_id else None,
            level=level,
            limit=int(limit or 20),
        )
        return {"ok": True, "count": len(results), "entries": results}
