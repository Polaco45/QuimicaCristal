# -*- coding: utf-8 -*-
"""Tool: schedule_activity — crea un mail.activity para seguimiento."""
import logging
from datetime import date, timedelta
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class ScheduleActivity(AgentTool):
    name = "schedule_activity"
    description = (
        "Crea una actividad de seguimiento (mail.activity) sobre un registro "
        "(típicamente un crm.lead o res.partner). La actividad le aparece al "
        "responsable en su tablero. "
        "Para deadline_offset_days: 0=hoy, 1=mañana, 7=en una semana, etc."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "res_model": {"type": "string", "description": "Modelo. Ej: 'crm.lead', 'res.partner'."},
            "res_id": {"type": "integer"},
            "summary": {"type": "string", "description": "Resumen corto de la actividad."},
            "note": {"type": "string", "description": "Nota detallada (HTML permitido)."},
            "activity_type_name": {
                "type": "string",
                "description": "Nombre del tipo de actividad. Ej: 'Iniciativa de venta', 'Llamada', 'Reunión'.",
            },
            "deadline_offset_days": {
                "type": "integer",
                "description": "Días desde hoy hasta deadline. Default 1 (mañana).",
                "default": 1,
            },
            "user_id": {
                "type": "integer",
                "description": "Usuario asignado. Si no se pasa, queda el del lead.",
            },
        },
        "required": ["res_model", "res_id", "summary"],
    }

    def _execute(self, env, run=None, res_model=None, res_id=None, summary=None,
                 note=None, activity_type_name=None, deadline_offset_days=1,
                 user_id=None, **kwargs):
        if not (res_model and res_id and summary):
            return {"error": "res_model, res_id, summary son obligatorios"}

        # Resolver tipo de actividad
        ActivityType = env['mail.activity.type'].sudo()
        if activity_type_name:
            atype = ActivityType.search([('name', '=', activity_type_name)], limit=1)
        else:
            atype = ActivityType.search([], limit=1)
        if not atype:
            return {"error": "No se encontró ningún tipo de actividad"}

        # Resolver res_model_id
        IrModel = env['ir.model']
        try:
            res_model_id = IrModel._get_id(res_model)
        except Exception:
            return {"error": f"Modelo {res_model} no existe"}

        # Resolver user — v1.21: las actividades del bot van SIEMPRE al bot
        # (OdooBot), NUNCA a Joaco. Joaco no debe recibir actividades del agente.
        config = env['cristal.agent.config'].sudo().get_active()
        bot_uid = config.bot_user_id.id if config.bot_user_id else 1
        owner_uid = config.owner_user_id.id if config.owner_user_id else 18
        if not user_id or int(user_id) == owner_uid:
            user_id = bot_uid

        deadline = date.today() + timedelta(days=int(deadline_offset_days or 0))

        try:
            activity = env['mail.activity'].sudo().create({
                'res_model_id': res_model_id,
                'res_model': res_model,
                'res_id': int(res_id),
                'activity_type_id': atype.id,
                'summary': summary,
                'note': note or '',
                'date_deadline': deadline,
                'user_id': user_id,
            })
        except Exception as e:
            return {"error": f"No se pudo crear actividad: {e}"}

        return {
            "ok": True,
            "activity_id": activity.id,
            "deadline": str(deadline),
            "summary": f"Actividad creada: {summary} (deadline {deadline})",
        }
