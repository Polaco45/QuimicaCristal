# -*- coding: utf-8 -*-
"""
Tool: set_origin (v1.61, punto 15 de captación)

Guarda cómo nos conoció un contacto nuevo que llegó sin código de origen (o con el
genérico ORGANICO). Claudio lo pregunta una sola vez, en el primer intercambio, y
guarda la respuesta. Nunca pisa un código que vino de un anuncio.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

SOURCES = {
    'anuncio_facebook': 'PAUTA-FB',
    'anuncio_instagram': 'PAUTA-IG',
    'instagram': 'ORG-IG',
    'facebook': 'ORG-FB',
    'google': 'GOOGLE',
    'recomendacion': 'REF',
    'vio_el_camion': 'CAMION',
    'local_o_cartel': 'LOCAL',
    'visita_vendedora': 'VISITA',
    'ya_era_cliente': 'CLIENTE',
    'otro': 'OTRO',
}


@ToolRegistry.register
class SetOrigin(AgentTool):
    name = "set_origin"
    description = (
        "Guardá cómo nos conoció el cliente cuando su origen es desconocido u ORGANICO "
        "(lo ves en el contexto). Preguntalo UNA sola vez, natural y corto, en el primer "
        "intercambio («¿Cómo nos conociste? ¿Por Instagram, un anuncio, una recomendación?») "
        "y guardá lo que conteste. Si nombra a quien lo recomendó, además usá register_referral."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del cliente."},
            "source": {"type": "string", "enum": list(SOURCES),
                       "description": "De dónde nos conoció."},
            "detail": {"type": "string", "description": "Lo que dijo, textual y corto."},
        },
        "required": ["partner_id", "source"],
    }

    def _execute(self, env, run=None, partner_id=None, source=None, detail=None, **kwargs):
        partner = env['res.partner'].sudo().browse(int(partner_id or 0))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}
        if source not in SOURCES:
            return {"error": "source inválido: " + ", ".join(SOURCES)}
        current = partner.agent_origin_code or ''
        if current and current != 'ORGANICO':
            return {"ok": True, "summary": f"Ya tenía origen {current}: no se cambia."}
        code = SOURCES[source]
        from odoo import fields as ofields
        vals = {'agent_origin_code': code}
        if not partner.agent_origin_date:
            vals['agent_origin_date'] = ofields.Datetime.now()
        if detail:
            vals['agent_origin_text'] = f"(respondió) {detail.strip()}"[:200]
        partner.write(vals)
        _logger.info("🧭 %s: origen %s (%s)", partner.name, code, detail or '')
        return {"ok": True, "summary": f"Origen guardado: {code}. No lo vuelvas a preguntar."}
