# -*- coding: utf-8 -*-
"""Tool: mark_activity_done — marca una mail.activity como completada."""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class MarkActivityDone(AgentTool):
    name = "mark_activity_done"
    description = (
        "Marca una actividad como completada. Si pasás feedback, queda como "
        "comentario al cerrarla."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "activity_id": {"type": "integer"},
            "feedback": {"type": "string"},
        },
        "required": ["activity_id"],
    }

    def _execute(self, env, run=None, activity_id=None, feedback=None, **kwargs):
        if not activity_id:
            return {"error": "activity_id es obligatorio"}

        activity = env['mail.activity'].sudo().browse(int(activity_id))
        if not activity.exists():
            return {"error": f"activity_id={activity_id} no existe"}

        try:
            activity.action_feedback(feedback=feedback or '')
        except Exception as e:
            return {"error": f"No se pudo cerrar actividad: {e}"}

        return {"ok": True, "summary": f"Actividad {activity_id} cerrada"}
