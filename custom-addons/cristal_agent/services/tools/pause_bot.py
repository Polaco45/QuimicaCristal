# -*- coding: utf-8 -*-
"""
Tool: pause_bot

Activa el takeover humano para un cliente. El bot deja de responderle por
X horas (o indefinidamente) hasta que un humano lo retome.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class PauseBot(AgentTool):
    name = "pause_bot"
    description = (
        "Pausa el bot para un cliente puntual. El bot deja de responderle automáticamente. "
        "Útil cuando ya escalaste algo y querés que Joaco maneje el cliente directo. "
        "duration_hours: cuántas horas pausarlo (default 1). 0 = indefinido."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer"},
            "reason": {"type": "string", "description": "Motivo de la pausa."},
            "duration_hours": {
                "type": "integer",
                "description": "Horas de pausa. 0 = indefinido. Default 1.",
                "default": 1,
            },
        },
        "required": ["partner_id", "reason"],
    }

    def _execute(self, env, run=None, partner_id=None, reason=None,
                 duration_hours=1, **kwargs):
        if not partner_id:
            return {"error": "partner_id es obligatorio"}

        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        Memory = env['cristal.agent.memory'].sudo()
        memory = Memory.get_or_create(partner)
        memory.activate_takeover(reason=reason or "Pausa manual del agente",
                                 duration_hours=int(duration_hours or 1))

        return {
            "ok": True,
            "partner_id": partner.id,
            "duration_hours": duration_hours,
            "summary": (
                f"Bot pausado para {partner.name} "
                f"({'indefinido' if not duration_hours else f'{duration_hours}h'})"
            ),
        }
