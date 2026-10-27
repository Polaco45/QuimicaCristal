# -*- coding: utf-8 -*-
"""
Tool: mark_opt_out (v1.42)

Saca a un cliente del flujo de venta cuando dice que no le interesa, que no vende
limpieza, que cerró, o que no le escriban más. No recibe cadencias, seguimientos,
envíos de los lunes ni avisos de la ruta. Si después vuelve a pedir productos, se
desmarca con undo=True.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

KINDS = {
    'no_interesa': 'no le interesa comprarnos',
    'no_vende': 'no vende productos de limpieza',
    'cerro': 'cerró o dejó el negocio',
    'no_escribir': 'pidió que no le escriban más',
}


@ToolRegistry.register
class MarkOptOut(AgentTool):
    name = "mark_opt_out"
    description = (
        "Sacá al cliente del flujo de venta (no más propuestas, seguimientos ni envíos) "
        "cuando lo dice CLARO: no le interesa comprarnos, no vende limpieza / no es "
        "revendedor, cerró el negocio, o pide que no le escriban más. NO lo uses si "
        "solo rechaza una promo o dice 'esta semana no' / 'más adelante'. Después "
        "despedite con UNA línea cordial (sin insistir). Si un cliente marcado vuelve "
        "a pedir productos, llamalo con undo=true."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del cliente."},
            "kind": {
                "type": "string",
                "enum": list(KINDS),
                "description": "no_interesa | no_vende | cerro | no_escribir",
            },
            "quote": {
                "type": "string",
                "description": "Lo que dijo el cliente, textual y corto.",
            },
            "undo": {
                "type": "boolean",
                "description": "true = vuelve al flujo de venta (pidió productos de nuevo).",
            },
        },
        "required": ["partner_id"],
    }

    def _execute(self, env, run=None, partner_id=None, kind=None, quote=None,
                 undo=False, **kwargs):
        partner = env['res.partner'].sudo().browse(int(partner_id or 0))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}
        if undo:
            partner.set_agent_opt_out("volvió a pedir productos", active=False)
            return {"ok": True, "summary": f"{partner.name} vuelve al flujo de venta."}
        if kind not in KINDS:
            return {"error": "Falta kind: no_interesa | no_vende | cerro | no_escribir"}
        reason = KINDS[kind] + (f' ("{quote.strip()[:150]}")' if quote else '')
        partner.set_agent_opt_out(reason)
        _logger.info("⛔ %s marcado No contactar: %s", partner.name, reason)
        return {"ok": True, "summary": (
            f"{partner.name} quedó fuera del flujo de venta ({KINDS[kind]}). No le "
            f"mandes más propuestas. Despedite con una línea cordial, sin insistir.")}
