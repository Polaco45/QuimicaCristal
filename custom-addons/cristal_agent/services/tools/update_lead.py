# -*- coding: utf-8 -*-
"""Tool: update_lead — actualiza un crm.lead."""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class UpdateLead(AgentTool):
    name = "update_lead"
    description = (
        "Actualiza un lead de CRM. Útil para mover de etapa, actualizar la fase "
        "comercial, agregar notas, registrar que la muestra fue enviada, etc."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "lead_id": {"type": "integer"},
            "stage_name": {"type": "string", "description": "Nombre de la etapa CRM (crm.stage). Ej: 'Calificado', 'Propuesta'."},
            "agent_strategy_phase": {
                "type": "string",
                "enum": ["phase_1", "phase_2", "phase_3", "phase_4", "phase_5", "won", "lost"],
            },
            "expected_revenue": {"type": "number"},
            "description": {"type": "string"},
            "mark_sample_sent": {"type": "boolean", "description": "Si True, marca agent_sample_sent_at = ahora."},
            "mark_sample_received": {"type": "boolean"},
            "mark_first_purchase": {"type": "boolean"},
            "first_purchase_amount": {"type": "number"},
            "mark_kit_sent": {"type": "boolean"},
        },
        "required": ["lead_id"],
    }

    def _execute(self, env, run=None, lead_id=None, **kwargs):
        if not lead_id:
            return {"error": "lead_id es obligatorio"}

        from odoo import fields
        lead = env['crm.lead'].sudo().browse(int(lead_id))
        if not lead.exists():
            return {"error": f"lead_id={lead_id} no existe"}

        vals = {}
        if kwargs.get('stage_name'):
            stage = env['crm.stage'].sudo().search([('name', '=', kwargs['stage_name'])], limit=1)
            if stage:
                vals['stage_id'] = stage.id
        for f in ('agent_strategy_phase', 'expected_revenue', 'description'):
            if kwargs.get(f) is not None:
                vals[f] = kwargs[f]

        now = fields.Datetime.now()
        if kwargs.get('mark_sample_sent'):
            vals['agent_sample_sent_at'] = now
        if kwargs.get('mark_sample_received'):
            vals['agent_sample_received_at'] = now
        if kwargs.get('mark_first_purchase'):
            vals['agent_first_purchase_at'] = now
            if kwargs.get('first_purchase_amount'):
                vals['agent_first_purchase_amount'] = float(kwargs['first_purchase_amount'])
        if kwargs.get('mark_kit_sent'):
            vals['agent_kit_sent'] = True
            vals['agent_kit_sent_at'] = now

        if not vals:
            return {"error": "No se especificó ningún campo a actualizar"}

        try:
            lead.write(vals)
        except Exception as e:
            return {"error": f"No se pudo actualizar lead: {e}"}

        return {
            "ok": True,
            "lead_id": lead.id,
            "updated_fields": list(vals.keys()),
            "summary": f"Lead {lead.name} actualizado",
        }
