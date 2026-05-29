# -*- coding: utf-8 -*-
"""
Tool: set_partner_level

Aplica un nivel BRONCE/PLATA/ORO a un cliente. Si baja de nivel, le da un
mes de gracia (mantiene los beneficios del nivel viejo durante un mes más).
"""
import logging
from datetime import date, timedelta
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

LEVEL_RANK = {'none': 0, 'bronce': 1, 'plata': 2, 'oro': 3}


@ToolRegistry.register
class SetPartnerLevel(AgentTool):
    name = "set_partner_level"
    description = (
        "Aplica un nivel mayorista (none/bronce/plata/oro) a un cliente. "
        "Si el nuevo nivel es MENOR que el actual, automáticamente le setea un "
        "mes de gracia (1 mes desde hoy) durante el cual mantiene los beneficios "
        "del nivel viejo. Si sube de nivel, se aplica de inmediato. "
        "Esta tool NO manda mensaje al cliente — usá send_whatsapp después si querés "
        "comunicárselo."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer"},
            "new_level": {
                "type": "string",
                "enum": ["none", "bronce", "plata", "oro"],
            },
            "skip_grace_period": {
                "type": "boolean",
                "description": "Si es True, en caso de bajada NO le da mes de gracia. Default False.",
                "default": False,
            },
        },
        "required": ["partner_id", "new_level"],
    }

    def _execute(self, env, run=None, partner_id=None, new_level=None,
                 skip_grace_period=False, **kwargs):
        if not (partner_id and new_level):
            return {"error": "partner_id y new_level son obligatorios"}

        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        old_level = partner.agent_level or 'none'

        if new_level not in LEVEL_RANK:
            return {"error": f"new_level inválido: {new_level}"}

        old_rank = LEVEL_RANK[old_level]
        new_rank = LEVEL_RANK[new_level]
        direction = 'same'
        if new_rank > old_rank:
            direction = 'up'
        elif new_rank < old_rank:
            direction = 'down'

        from odoo import fields as odoo_fields
        vals = {
            'agent_level': new_level,
            'agent_level_computed_at': odoo_fields.Datetime.now(),
        }

        # Si bajó y no se skip, mes de gracia
        grace_until = None
        if direction == 'down' and not skip_grace_period:
            grace_until = date.today() + timedelta(days=30)
            vals['agent_grace_period_until'] = grace_until
        else:
            vals['agent_grace_period_until'] = False

        try:
            partner.write(vals)
        except Exception as e:
            return {"error": f"No se pudo aplicar el nivel: {e}"}

        # Observación automática del cambio
        if direction != 'same':
            partner.append_agent_observation(
                f"Nivel cambió: {old_level.upper()} → {new_level.upper()} "
                f"({'subió' if direction == 'up' else 'bajó'})"
                + (f" [gracia hasta {grace_until}]" if grace_until else "")
            )

        return {
            "ok": True,
            "partner_id": partner.id,
            "old_level": old_level,
            "new_level": new_level,
            "direction": direction,
            "grace_until": str(grace_until) if grace_until else None,
            "summary": (
                f"Nivel de {partner.name}: {old_level.upper()} → {new_level.upper()}"
                + (f" (gracia hasta {grace_until})" if grace_until else "")
            ),
        }
