# -*- coding: utf-8 -*-
"""
Tool: add_knowledge

Guarda una nueva entry en la base de conocimiento. Esta es la pieza que
permite que el agente "aprenda" cosas que Joaco le enseña.

Cuándo lo usás:
- Joaco te dice en el chat interno "anotate que tal cosa", "recordá X",
  "a partir de hoy hacemos Y".
- Detectás un patrón en un cliente que vale la pena guardar como observación.
- Querés guardar una FAQ nueva que apareció.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class AddKnowledge(AgentTool):
    name = "add_knowledge"
    description = (
        "Guarda una entry nueva en la base de conocimiento del agente. Usalo cuando "
        "Joaco te enseña algo, o cuando aprendés un patrón que conviene recordar para "
        "futuras interacciones. La entry queda activa indefinidamente, salvo que pases "
        "valid_until. La próxima vez que el agente arranque, la va a leer."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Título corto descriptivo. Ej: 'Lunes y miércoles 15% off baño'.",
            },
            "category": {
                "type": "string",
                "enum": ["precio", "politica_comercial", "oferta_activa", "producto",
                         "regla_negocio", "observacion_cliente", "faq", "evento",
                         "estrategia_marketing", "otro"],
            },
            "content": {
                "type": "string",
                "description": "Contenido completo. Lo que el agente va a leer al consultar.",
            },
            "applies_to": {
                "type": "string",
                "enum": ["all", "level_bronce", "level_plata", "level_oro", "specific_partners"],
                "default": "all",
            },
            "partner_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Solo si applies_to='specific_partners'.",
            },
            "valid_until": {
                "type": "string",
                "description": "Fecha YYYY-MM-DD hasta cuando es vigente (opcional).",
            },
            "priority": {
                "type": "integer",
                "default": 10,
                "description": "Prioridad. Mayor = se lee primero.",
            },
            "source": {
                "type": "string",
                "enum": ["chat_joaco", "auto_observation", "manual"],
                "default": "chat_joaco",
            },
        },
        "required": ["name", "category", "content"],
    }

    def _execute(self, env, run=None, name=None, category=None, content=None,
                 applies_to='all', partner_ids=None, valid_until=None,
                 priority=10, source='chat_joaco', **kwargs):
        if not (name and category and content):
            return {"error": "name, category y content son obligatorios"}

        vals = {
            'name': name,
            'category': category,
            'content': content,
            'applies_to': applies_to,
            'priority': int(priority or 10),
            'source': source,
            'active': True,
        }
        if valid_until:
            vals['valid_until'] = valid_until
        if applies_to == 'specific_partners' and partner_ids:
            vals['partner_ids'] = [(6, 0, [int(pid) for pid in partner_ids])]

        try:
            entry = env['cristal.agent.knowledge'].sudo().create(vals)
        except Exception as e:
            return {"error": f"No se pudo crear entry: {e}"}

        return {
            "ok": True,
            "knowledge_id": entry.id,
            "summary": f"Conocimiento guardado: [{category}] {name}",
        }
