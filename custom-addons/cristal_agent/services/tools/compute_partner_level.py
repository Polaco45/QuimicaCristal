# -*- coding: utf-8 -*-
"""
Tool: compute_partner_level

Calcula el nivel mayorista (BRONCE/PLATA/ORO) de un cliente basándose en
su volumen mensual promedio (últimos 3 meses, según facturas posted).

Umbrales:
- BRONCE: $50.000 - $199.999
- PLATA: $200.000 - $499.999
- ORO: $500.000+
- (Sin nivel): <$50.000
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

LEVEL_THRESHOLDS = [
    (500_000, 'oro'),
    (200_000, 'plata'),
    (50_000, 'bronce'),
    (0, 'none'),
]


@ToolRegistry.register
class ComputePartnerLevel(AgentTool):
    name = "compute_partner_level"
    description = (
        "Calcula el nivel mayorista de un cliente (BRONCE/PLATA/ORO) basándose en su "
        "volumen mensual promedio de los últimos 3 meses (facturas confirmadas). "
        "Umbrales: BRONCE >=$50k, PLATA >=$200k, ORO >=$500k. "
        "Devuelve el nivel calculado SIN aplicarlo. Para aplicarlo usá set_partner_level."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer"},
            "months_to_average": {
                "type": "integer",
                "description": "Cantidad de meses para promediar (default 3).",
                "default": 3,
            },
        },
        "required": ["partner_id"],
    }

    def _execute(self, env, run=None, partner_id=None, months_to_average=3, **kwargs):
        if not partner_id:
            return {"error": "partner_id es obligatorio"}

        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        avg_volume = partner.compute_monthly_volume(months=int(months_to_average or 3))

        # Determinar nivel
        computed_level = 'none'
        for threshold, level in LEVEL_THRESHOLDS:
            if avg_volume >= threshold:
                computed_level = level
                break

        return {
            "ok": True,
            "partner_id": partner.id,
            "partner_name": partner.name,
            "monthly_volume_avg": round(avg_volume, 2),
            "current_level": partner.agent_level or 'none',
            "computed_level": computed_level,
            "level_changed": computed_level != (partner.agent_level or 'none'),
            "summary": (
                f"{partner.name}: volumen mensual promedio ${avg_volume:,.0f} "
                f"→ nivel calculado: {computed_level.upper()} "
                f"(actual: {(partner.agent_level or 'none').upper()})"
            ),
        }
