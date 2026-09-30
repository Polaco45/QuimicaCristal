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
            "city": {
                "type": "string",
                "description": "Ciudad/localidad del cliente, tal como la dice. Guardala "
                               "SIEMPRE que la sepas: la tool la normaliza sola (grafía "
                               "canónica), resuelve la zona y el circuito de la ruta del "
                               "camión, y completa la calificación. NO hace falta que "
                               "pases agent_zone si pasás city.",
            },
            "agent_zone": {
                "type": "string",
                "enum": ['rio_cuarto', 'las_higueras', 'ruta_camion', 'fuera_zona',
                         'other', 'unknown'],
                "description": "Zona de reparto. Si pasás city, se calcula sola (gana la "
                               "ciudad). 'rio_cuarto'/'las_higueras' = reparto normal; "
                               "'ruta_camion' = localidad de un circuito del camión (jueves); "
                               "'fuera_zona' = fuera de los circuitos (auto-etiqueta "
                               "'Fuera de zona').",
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

        # ── Ruta del camión (v1.32): la ciudad define zona + circuito ──
        # Normaliza la ciudad a su grafía canónica y calcula agent_zone (gana la
        # ciudad sobre lo que haya adivinado el bot). Mutamos kwargs para que el
        # loop de ALLOWED_FIELDS escriba los valores ya normalizados.
        route_info = None
        if kwargs.get('city'):
            route_info = self._resolve_city(env, partner, kwargs)

        vals = {}
        for f in ALLOWED_FIELDS:
            if f in kwargs and kwargs[f] is not None:
                vals[f] = kwargs[f]
        if route_info and route_info.get('truck_circuit_id'):
            vals['truck_circuit_id'] = route_info['truck_circuit_id']
        if route_info and route_info.get('remove_fuera_zona_tag'):
            vals['category_id'] = vals.get('category_id', []) + [
                (3, route_info['remove_fuera_zona_tag'])]

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

        # Calificación "mínimo real": la localidad es el dato obligatorio. Queda en
        # la memoria (qual_zone) y el cliente queda calificado cuando además
        # sabemos que es comercio que revende (etiqueta Mayorista).
        if route_info:
            try:
                mem = env['cristal.agent.memory'].sudo().get_or_create(partner)
                if mem:
                    mem_vals = {'qual_zone': route_info['canonical']}
                    if partner.is_mayorista():
                        mem_vals['qual_qualified'] = True
                    mem.write(mem_vals)
            except Exception as e:
                _logger.warning("No pude completar qual_zone para %s: %s", partner.id, e)

        result = {
            "ok": True,
            "partner_id": partner.id,
            "updated_fields": list(vals.keys()),
            "summary": f"Partner {partner.name} actualizado: {list(vals.keys())}",
        }
        if route_info:
            result.update({
                "city_canonical": route_info['canonical'],
                "zone": route_info['zone'],
                "truck_circuit": route_info.get('circuit_name'),
                "route_note": route_info['note'],
            })
        return result

    # ───────────────────────── Ruta del camión ─────────────────────────
    def _resolve_city(self, env, partner, kwargs):
        """Clasifica kwargs['city'] y deja en kwargs la ciudad canónica y la
        zona. Devuelve info para el resto del flujo. NUNCA pisa una etiqueta de
        circuito que el partner ya tenga (la fuente de verdad son las etiquetas)."""
        Circuit = env['cristal.agent.circuit'].sudo()
        info = Circuit.classify_city(kwargs['city'])
        if info['kind'] == 'empty':
            return None
        kwargs['city'] = info['canonical']

        circuits = Circuit.search([])
        circuit_cats = circuits.mapped('partner_category_id')
        existing_cat = partner.category_id & circuit_cats
        fz_tag = env['res.partner.category'].sudo().search(
            [('name', '=', 'Fuera de zona')], limit=1)

        out = {'canonical': info['canonical'], 'truck_circuit_id': False,
               'circuit_name': None, 'remove_fuera_zona_tag': False}

        if existing_cat:
            # Ya tiene etiqueta de circuito: gana la etiqueta, no la pisamos.
            circuit = circuits.filtered(
                lambda c: c.partner_category_id == existing_cat[0])[:1]
            kwargs['agent_zone'] = 'ruta_camion'
            out.update(zone='ruta_camion', circuit_name=circuit.name,
                       truck_circuit_id=circuit.id if not partner.truck_circuit_id else False,
                       note=f"Ya estaba en el circuito {circuit.name} (por etiqueta); "
                            f"se respeta.")
        elif info['kind'] == 'circuit':
            kwargs['agent_zone'] = 'ruta_camion'
            out.update(zone='ruta_camion', circuit_name=info['circuit'].name,
                       truck_circuit_id=info['circuit'].id,
                       note=f"{info['canonical']} está en el circuito "
                            f"{info['circuit'].name} (ruta del camión, jueves). Usá "
                            f"get_route_info para la fecha de paso. Cliente de pueblo: "
                            f"si es nuevo, tratalo de USTED.")
        elif info['kind'] == 'rio_cuarto':
            kwargs['agent_zone'] = ('las_higueras' if info['canonical'] == 'Las Higueras'
                                    else 'rio_cuarto')
            out.update(zone=kwargs['agent_zone'],
                       note="Río Cuarto: reparto normal por la mañana, NO los jueves.")
        else:  # fuera_zona
            kwargs['agent_zone'] = 'fuera_zona'
            out.update(zone='fuera_zona',
                       note=f"{info['canonical']} está FUERA de los 4 circuitos. NO "
                            f"ofrezcas condiciones de envío: si pregunta, decile que el "
                            f"envío a su localidad lo coordina Joaquín directamente y "
                            f"escalá a Joaco. Tratalo de USTED.")

        # Si ahora es Río Cuarto o un circuito, la etiqueta "Fuera de zona" es errónea
        # (y excluye al cliente de los broadcasts): se la sacamos.
        if out['zone'] != 'fuera_zona' and fz_tag and fz_tag in partner.category_id:
            out['remove_fuera_zona_tag'] = fz_tag.id
        return out
