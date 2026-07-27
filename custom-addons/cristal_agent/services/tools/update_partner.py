# -*- coding: utf-8 -*-
"""
Tool: update_partner

Actualiza datos de un partner existente. Útil para corregir nombre,
agregar email, cambiar dirección, agregar etiquetas, etc.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

# Campos que el agente puede actualizar (para no abrir todo res.partner)
ALLOWED_FIELDS = {
    'name', 'mobile', 'phone', 'email', 'street', 'street2', 'city',
    'state_id', 'country_id', 'vat', 'comment', 'website',
    'agent_strategy_phase', 'agent_observations', 'agent_zone',
}


@ToolRegistry.register
class UpdatePartner(AgentTool):
    name = "update_partner"
    description = (
        "Actualiza campos básicos de un cliente (res.partner). "
        "Pasale partner_id y los campos a actualizar. "
        "Si querés agregarle una etiqueta nueva, usá category_to_add (nombre de la etiqueta). "
        "Para cambiar el pricelist, usá pricelist_name."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer"},
            "name": {"type": "string"},
            "mobile": {"type": "string"},
            "email": {"type": "string"},
            "street": {"type": "string"},
            "city": {"type": "string", "description": "Ciudad/localidad del cliente. Guardala SIEMPRE que la sepas."},
            "agent_zone": {
                "type": "string",
                "enum": ['rio_cuarto', 'las_higueras', 'fuera_zona', 'other', 'unknown'],
                "description": "Zona de reparto. 'rio_cuarto'/'las_higueras' = entregamos; "
                               "'fuera_zona' = lead para expansión futura (auto-etiqueta "
                               "'Fuera de zona'). Clasificá SIEMPRE durante la calificación.",
            },
            "vat": {"type": "string"},
            "category_to_add": {
                "type": "string",
                "description": "Nombre de etiqueta a agregar. Ej: 'Mayorista'."
            },
            "category_to_remove": {
                "type": "string",
                "description": "Nombre de etiqueta a quitar."
            },
            "pricelist_name": {
                "type": "string",
                "description": "Nombre de la pricelist a asignar. Ej: 'Lista Mayorista'."
            },
            "agent_strategy_phase": {
                "type": "string",
                "enum": [
                    'not_qualified', 'disqualified_to_crilimp',
                    'phase_1_qualifying', 'phase_1_qualified',
                    'phase_2_post_sample',
                    'phase_3_first_purchase_done', 'phase_3_onboarding',
                    'phase_4_active_customer', 'phase_5_loyalty',
                    'churning', 'lost', 'reactivated',
                ],
                "description": "Actualizá la fase comercial del cliente.",
            },
        },
        "required": ["partner_id"],
    }

    def _execute(self, env, run=None, partner_id=None, **kwargs):
        if not partner_id:
            return {"error": "partner_id es obligatorio"}

        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        vals = {}
        for f in ALLOWED_FIELDS:
            if f in kwargs and kwargs[f] is not None:
                vals[f] = kwargs[f]

        # Etiqueta a agregar
        if kwargs.get('category_to_add'):
            tag = env['res.partner.category'].sudo().search(
                [('name', '=', kwargs['category_to_add'])], limit=1
            )
            if tag:
                vals['category_id'] = vals.get('category_id', []) + [(4, tag.id)]
            else:
                return {"error": f"Etiqueta '{kwargs['category_to_add']}' no existe"}

        # Etiqueta a remover
        if kwargs.get('category_to_remove'):
            tag = env['res.partner.category'].sudo().search(
                [('name', '=', kwargs['category_to_remove'])], limit=1
            )
            if tag:
                vals['category_id'] = vals.get('category_id', []) + [(3, tag.id)]

        # Auto-etiqueta "Fuera de zona" cuando se marca agent_zone=fuera_zona
        # (para que aparezca en filtros y se excluya de broadcasts).
        if kwargs.get('agent_zone') == 'fuera_zona':
            fz_tag = env['res.partner.category'].sudo().search(
                [('name', '=', 'Fuera de zona')], limit=1
            )
            if fz_tag:
                vals['category_id'] = vals.get('category_id', []) + [(4, fz_tag.id)]

        # Pricelist
        if kwargs.get('pricelist_name'):
            pl = env['product.pricelist'].sudo().search(
                [('name', '=', kwargs['pricelist_name'])], limit=1
            )
            if pl:
                vals['property_product_pricelist'] = pl.id

        # Al etiquetar MAYORISTA, asegurar la Lista Mayorista como pricelist del
        # partner (raíz del bug: partners consumidor final re-etiquetados mayorista
        # conservaban L.C 1, y aunque la cotización ya se fuerza a Lista Mayorista,
        # dejar la ficha bien evita que otros flujos coticen con precio CF).
        if (kwargs.get('category_to_add') or '').strip().lower() == 'mayorista' \
                and 'property_product_pricelist' not in vals:
            mayorista_pl = env['product.pricelist'].sudo().search(
                [('name', '=', 'Lista Mayorista')], limit=1)
            if mayorista_pl:
                vals['property_product_pricelist'] = mayorista_pl.id

        if not vals:
            return {"error": "No se especificó ningún campo válido para actualizar"}

        try:
            partner.write(vals)
        except Exception as e:
            return {"error": f"No se pudo actualizar el partner: {e}"}

        return {
            "ok": True,
            "partner_id": partner.id,
            "updated_fields": list(vals.keys()),
            "summary": f"Partner {partner.name} actualizado: {list(vals.keys())}",
        }
