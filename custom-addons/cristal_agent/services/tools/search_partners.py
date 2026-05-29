# -*- coding: utf-8 -*-
"""
Tool: search_partners

Busca partners (clientes) en res.partner por nombre, mobile, email o id.
"""
import logging
import re
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


def _sanitize_phone(phone):
    if not phone:
        return ''
    return '+' + re.sub(r'\D', '', phone)


@ToolRegistry.register
class SearchPartners(AgentTool):
    name = "search_partners"
    description = (
        "Busca clientes (res.partner) en la base de datos. "
        "Podés buscar por mobile, name (nombre), email, vat (CUIT) o id directo. "
        "Devuelve lista de matches con sus datos básicos. "
        "Si querés más detalle de un cliente puntual, después usá read_partner."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "mobile": {
                "type": "string",
                "description": "Número de teléfono. Lo sanitizamos automáticamente. Ej: '+5493585481191', '358-548-1191'.",
            },
            "name": {
                "type": "string",
                "description": "Nombre o parte del nombre. Búsqueda case-insensitive.",
            },
            "email": {
                "type": "string",
                "description": "Email o parte del email.",
            },
            "vat": {
                "type": "string",
                "description": "CUIT/DNI.",
            },
            "id": {
                "type": "integer",
                "description": "ID exacto del partner.",
            },
            "category_name": {
                "type": "string",
                "description": "Filtrar por etiqueta. Ej: 'Mayorista', 'Consumidor Final', 'EMPRESA'.",
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de resultados (default 10, máx 50).",
                "default": 10,
            },
        },
    }

    def _execute(self, env, run=None, mobile=None, name=None, email=None,
                 vat=None, id=None, category_name=None, limit=10, **kwargs):
        Partner = env['res.partner'].sudo()
        limit = max(1, min(50, int(limit or 10)))

        domain = []
        if id:
            domain.append(('id', '=', int(id)))
        if mobile:
            sanitized = _sanitize_phone(mobile)
            phone_domain = ['|', ('phone_sanitized', '=', sanitized),
                            ('phone_sanitized', 'ilike', sanitized[-10:])]
            # También probamos con/sin '9' argentino
            if sanitized.startswith('+549'):
                without_9 = '+54' + sanitized[4:]
                phone_domain = ['|', '|',
                                ('phone_sanitized', '=', sanitized),
                                ('phone_sanitized', '=', without_9),
                                ('phone_sanitized', 'ilike', sanitized[-10:])]
            domain.extend(phone_domain)
        if name:
            domain.append(('name', 'ilike', name))
        if email:
            domain.append(('email', 'ilike', email))
        if vat:
            domain.append(('vat', '=', vat))
        if category_name:
            tag = env['res.partner.category'].sudo().search(
                [('name', '=', category_name)], limit=1
            )
            if tag:
                domain.append(('category_id', 'in', [tag.id]))

        if not domain:
            return {"error": "Tenés que pasar al menos un criterio de búsqueda"}

        partners = Partner.search(domain, limit=limit)

        result = []
        for p in partners:
            result.append({
                'id': p.id,
                'name': p.name or '',
                'mobile': p.mobile or p.phone or '',
                'email': p.email or '',
                'vat': p.vat or '',
                'is_company': p.is_company,
                'categories': [c.name for c in p.category_id],
                'agent_level': p.agent_level if hasattr(p, 'agent_level') else 'none',
                'agent_strategy_phase': p.agent_strategy_phase if hasattr(p, 'agent_strategy_phase') else 'not_qualified',
            })

        return {"ok": True, "count": len(result), "partners": result}
