# -*- coding: utf-8 -*-
"""
Tool: create_partner

Crea un partner nuevo (cliente). Aplica las etiquetas, lista de precios y
team de venta correspondientes según el tipo (CF, Mayorista, Empresa).
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


# Mapeos según el system prompt de Claudio
CATEGORY_NAME_TO_CONFIG = {
    'consumidor_final': {
        'category_name': 'Consumidor Final',
        'pricelist_name': 'L.C 1',
        'team_name': None,
        'is_company': False,
    },
    'mayorista': {
        'category_name': 'Mayorista',
        'pricelist_name': 'Lista Mayorista',
        'team_name': 'Cristal Mayorista',
        'is_company': False,
    },
    'empresa': {
        'category_name': 'EMPRESA',
        'pricelist_name': 'L.E 2',
        'team_name': 'Ventas',
        'is_company': True,
    },
}


@ToolRegistry.register
class CreatePartner(AgentTool):
    name = "create_partner"
    description = (
        "Crea un cliente nuevo (res.partner) con las etiquetas, pricelist y team correctos "
        "según el tipo. Usalo cuando un cliente nuevo termina la calificación o cuando "
        "identificás un cliente que no estaba en la base. "
        "Tipos válidos: 'consumidor_final', 'mayorista', 'empresa'. "
        "Para empresa, marca is_company=True automáticamente."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Nombre del cliente (persona o empresa).",
            },
            "client_type": {
                "type": "string",
                "enum": ["consumidor_final", "mayorista", "empresa"],
                "description": "Tipo de cliente. Define etiqueta, pricelist y team.",
            },
            "mobile": {
                "type": "string",
                "description": "Teléfono móvil con +código país. Ej: '+5493585481191'.",
            },
            "email": {
                "type": "string",
                "description": "Email del cliente (opcional).",
            },
            "street": {
                "type": "string",
                "description": "Dirección (opcional).",
            },
            "city": {
                "type": "string",
                "description": "Ciudad (opcional).",
            },
            "vat": {
                "type": "string",
                "description": "CUIT/DNI (opcional).",
            },
            "parent_partner_id": {
                "type": "integer",
                "description": "Si es un contacto de una empresa, el id de la empresa madre.",
            },
        },
        "required": ["name", "client_type"],
    }

    def _execute(self, env, run=None, name=None, client_type=None, mobile=None,
                 email=None, street=None, city=None, vat=None,
                 parent_partner_id=None, **kwargs):
        if not (name and client_type):
            return {"error": "name y client_type son obligatorios"}

        if client_type not in CATEGORY_NAME_TO_CONFIG:
            return {"error": f"client_type inválido. Usá: {list(CATEGORY_NAME_TO_CONFIG.keys())}"}

        cfg = CATEGORY_NAME_TO_CONFIG[client_type]

        # Resolver etiqueta
        Tag = env['res.partner.category'].sudo()
        category = Tag.search([('name', '=', cfg['category_name'])], limit=1)
        if not category:
            return {"error": f"Etiqueta '{cfg['category_name']}' no existe en res.partner.category"}

        # Resolver pricelist
        Pricelist = env['product.pricelist'].sudo()
        pricelist = Pricelist.search([('name', '=', cfg['pricelist_name'])], limit=1)
        pricelist_id = pricelist.id if pricelist else False

        # Resolver team
        team_id = False
        if cfg['team_name']:
            Team = env['crm.team'].sudo()
            team = Team.search([('name', '=', cfg['team_name'])], limit=1)
            team_id = team.id if team else False

        # Construir vals
        vals = {
            'name': name,
            'is_company': cfg['is_company'],
            'category_id': [(4, category.id)],
        }
        if mobile:
            vals['mobile'] = mobile
        if email:
            vals['email'] = email
        if street:
            vals['street'] = street
        if city:
            vals['city'] = city
        if vat:
            vals['vat'] = vat
        if pricelist_id:
            vals['property_product_pricelist'] = pricelist_id
        if team_id:
            vals['team_id'] = team_id
        if parent_partner_id:
            vals['parent_id'] = int(parent_partner_id)

        # Setear fase comercial inicial si es Mayorista
        if client_type == 'mayorista':
            vals['agent_strategy_phase'] = 'phase_1_qualifying'

        try:
            partner = env['res.partner'].sudo().create(vals)
        except Exception as e:
            _logger.exception("Error creando partner: %s", e)
            return {"error": f"No se pudo crear el partner: {e}"}

        # Crear memoria asociada
        env['cristal.agent.memory'].sudo().get_or_create(partner)

        return {
            "ok": True,
            "partner_id": partner.id,
            "name": partner.name,
            "category": cfg['category_name'],
            "pricelist": cfg['pricelist_name'],
            "team": cfg['team_name'] or '(ninguno)',
            "summary": f"Partner creado: {partner.name} (id={partner.id}, tipo={client_type})",
        }
