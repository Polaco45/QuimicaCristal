# -*- coding: utf-8 -*-
"""
Tool: update_observation

Agrega una observación al campo agent_observations del partner.
Usalo cuando aprendiste algo del cliente que conviene recordar.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class UpdateObservation(AgentTool):
    name = "update_observation"
    description = (
        "Agrega una observación al historial del cliente. "
        "Lo escribís como si fueras un empleado tomando nota: "
        "'Le interesa el formato de 5L', 'Pidió cotización pero no respondió', "
        "'Es exigente con los plazos', 'Recomendó a otro mayorista', etc. "
        "Las observaciones quedan acumuladas y las vas a leer en futuras interacciones. "
        "Sé conciso: 1-2 líneas máximo por observación. NO repitas observaciones similares."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {
                "type": "integer",
                "description": "ID del cliente.",
            },
            "observation": {
                "type": "string",
                "description": "Observación corta (máx 200 caracteres recomendado).",
            },
        },
        "required": ["partner_id", "observation"],
    }

    def _execute(self, env, run=None, partner_id=None, observation=None, **kwargs):
        if not (partner_id and observation):
            return {"error": "partner_id y observation son obligatorios"}

        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        # Limitar a 300 caracteres por observación
        text = observation.strip()[:300]
        partner.append_agent_observation(text)

        return {
            "ok": True,
            "partner_id": partner.id,
            "observation": text,
            "summary": f"Observación agregada para {partner.name}",
        }
