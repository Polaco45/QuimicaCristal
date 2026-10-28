# -*- coding: utf-8 -*-
"""
Tool: set_promo_consent (v1.44)

Anota si el cliente acepta que le avisemos por WhatsApp (recordatorio de reposición y
promos). Los campos son de cristal_minorista; si ese módulo no está, no hace nada.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class SetPromoConsent(AgentTool):
    name = "set_promo_consent"
    description = (
        "Anotá si el cliente acepta que le avisemos por WhatsApp cuando se le esté por "
        "terminar algo y cuando haya promos. accepted=true cuando dice que sí; "
        "accepted=false cuando pide no recibir promos (puede seguir comprando normal). "
        "Preguntalo UNA sola vez y solo si su bloque dice 'todavía no se le preguntó'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del cliente."},
            "accepted": {"type": "boolean", "description": "true = acepta avisos; false = no quiere promos."},
        },
        "required": ["partner_id", "accepted"],
    }

    def _execute(self, env, run=None, partner_id=None, accepted=None, **kwargs):
        partner = env['res.partner'].sudo().browse(int(partner_id or 0))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}
        if 'cristal_mkt_optin' not in partner._fields:
            return {"ok": False, "summary": "El registro de avisos no está instalado; seguí normal."}
        if accepted:
            partner.write({'cristal_mkt_optin': True, 'cristal_mkt_optin_source': 'whatsapp'})
            summary = f"{partner.name} acepta avisos por WhatsApp. Agradecele en media línea."
        else:
            partner.write({'cristal_mkt_optout': True})
            summary = f"{partner.name} no quiere promos. No se las ofrezcas por iniciativa propia."
        _logger.info("📣 Avisos WhatsApp %s: %s", partner.name, accepted)
        return {"ok": True, "summary": summary}
