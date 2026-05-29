# -*- coding: utf-8 -*-
"""
Tool: complete_institutional_qualification

v1.9.1 — Cierre ATÓMICO del flow institucional Plan Control.

Toma los datos de qualification_data (acumulados por update_qualification_data)
y ejecuta TODO en una sola operación transaccional:

1. Crea o actualiza la EMPRESA (res.partner con is_company=True si necesita factura,
   o el contacto directo si no necesita).
2. Crea o vincula el SUBCONTACTO bajo la empresa (si hay empresa formal).
3. Crea el LEAD en stage 'Calificado' (id 14) asignado a Joaco.
4. Crea la ACTIVIDAD tipo 'Visitar Institucion' (id 3) para Joaco, deadline hoy.
5. Actualiza memory:
   - human_takeover = True
   - flow_state = 'inst_handed_over'
   - qual_qualified = True
   - lead_id = <id del lead creado>
   - client_type = 'institucional'
   - qualification_data = {}  (limpieza)

Si CUALQUIER paso falla, se hace rollback completo vía savepoint Postgres.

ZONA: si city no es Río Cuarto ni Las Higueras, devuelve error y el bot
debe descalificar al cliente amable. NO crea nada.
"""
import logging
from datetime import date
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

# IDs de producción confirmados
COUNTRY_AR = 10
STATE_CORDOBA = 558
PRICELIST_LE2 = 33
STAGE_CALIFICADO = 14
TEAM_VENTAS = 1
USER_JOACO = 18
ACTIVITY_VISITAR_INSTITUCION = 3
CATEGORY_EMPRESA = 1

# Ciudades válidas (case insensitive, normalizadas sin acentos)
VALID_CITIES_NORMALIZED = {
    'rio cuarto',
    'rio iv',
    'rio 4',
    'las higueras',
    'higueras',
}


def _normalize_city(city):
    """Normaliza una string de ciudad para comparar (lowercase, sin acentos)."""
    if not city:
        return ''
    s = city.lower().strip()
    replacements = {'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ñ': 'n'}
    for k, v in replacements.items():
        s = s.replace(k, v)
    return s


@ToolRegistry.register
class CompleteInstitutionalQualification(AgentTool):
    name = "complete_institutional_qualification"
    description = (
        "Cierra ATÓMICAMENTE la calificación institucional Plan Control. "
        "Toma los datos del qualification_data acumulado y en UNA sola "
        "transacción: crea/actualiza empresa + subcontacto (si factura) + "
        "lead en stage Calificado + actividad para Joaco + activa takeover. "
        "Si city no es Río Cuarto ni Las Higueras, descalifica sin crear nada. "
        "Si cualquier paso falla, rollback completo. "
        "Llamala UNA SOLA VEZ al detectar que el cliente respondió la "
        "última pregunta (disponibilidad). DESPUÉS de esta tool, mandá el "
        "mensaje de cierre con el resumen al cliente."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {
                "type": "integer",
                "description": "ID del partner que está calificando.",
            },
            "qualification_data": {
                "type": "object",
                "description": (
                    "Datos completos de la calificación. Campos esperados: "
                    "contact_name (str), company_name (str), "
                    "rubro_label (str), rubro_partner_category_id (int), "
                    "necesita_factura (bool), fiscal_name (str, si factura), "
                    "vat (str, CUIT si factura), rol (str), "
                    "street (str), city (str), disponibilidad (str), "
                    "notas_extra (str, opcional)."
                ),
                "properties": {
                    "contact_name": {"type": "string"},
                    "company_name": {"type": "string"},
                    "rubro_label": {"type": "string"},
                    "rubro_partner_category_id": {"type": "integer"},
                    "necesita_factura": {"type": "boolean"},
                    "fiscal_name": {"type": "string"},
                    "vat": {"type": "string"},
                    "rol": {"type": "string"},
                    "street": {"type": "string"},
                    "city": {"type": "string"},
                    "disponibilidad": {"type": "string"},
                    "notas_extra": {"type": "string"},
                },
                "required": [
                    "contact_name", "rubro_label", "rubro_partner_category_id",
                    "necesita_factura", "rol", "street", "city", "disponibilidad",
                ],
            },
        },
        "required": ["partner_id", "qualification_data"],
    }

    def _execute(self, env, partner_id, qualification_data, **kwargs):
        if not partner_id:
            return {"ok": False, "error": "partner_id requerido"}

        data = qualification_data or {}

        # ── Validaciones previas (antes de la transacción) ──
        required = ['contact_name', 'rubro_label', 'rubro_partner_category_id',
                    'rol', 'street', 'city', 'disponibilidad']
        missing = [k for k in required if not data.get(k)]
        if missing:
            return {
                "ok": False,
                "error": f"Faltan datos: {', '.join(missing)}",
                "missing": missing,
            }

        # Validar zona ANTES de hacer cualquier escritura
        city_norm = _normalize_city(data.get('city', ''))
        if city_norm not in VALID_CITIES_NORMALIZED:
            # Fuera de zona — marcar memory y NO crear nada
            partner = env['res.partner'].sudo().browse(partner_id)
            if partner.exists():
                memory = env['cristal.agent.memory'].sudo().get_or_create(partner)
                memory.write({
                    'flow_state': 'inst_out_of_zone',
                    'qualification_data': data,  # guardamos para futuro
                })
            return {
                "ok": False,
                "out_of_zone": True,
                "city_received": data.get('city'),
                "error": (
                    f"Ciudad '{data.get('city')}' fuera de zona. "
                    "Solo Río Cuarto o Las Higueras. "
                    "Descalificá amable, NO crees lead. "
                    "Mensaje sugerido: 'Ah, por ahora solo cubrimos Río Cuarto "
                    "y Las Higueras. Te queda guardada tu consulta por si "
                    "ampliamos. Gracias igual.'"
                ),
            }

        # Validar factura + CUIT
        necesita_factura = bool(data.get('necesita_factura'))
        if necesita_factura:
            if not data.get('fiscal_name') or not data.get('vat'):
                return {
                    "ok": False,
                    "error": (
                        "Si necesita_factura=true, fiscal_name y vat son obligatorios. "
                        "Volvé a preguntar."
                    ),
                }

        # ── Cierre atómico con savepoint ──
        # El savepoint permite rollback solo de esta operación sin tirar
        # toda la request del bot.
        try:
            with env.cr.savepoint():
                result = self._do_atomic_close(env, partner_id, data)
            return result
        except Exception as e:
            _logger.exception("Error en cierre atómico institucional: %s", e)
            return {
                "ok": False,
                "error": f"Falló cierre atómico (rollback hecho): {str(e)[:200]}",
                "rollback": True,
            }

    def _do_atomic_close(self, env, partner_id, data):
        """Ejecuta los 5 pasos dentro del savepoint."""
        Partner = env['res.partner'].sudo()
        Lead = env['crm.lead'].sudo()
        Activity = env['mail.activity'].sudo()
        Memory = env['cristal.agent.memory'].sudo()

        # Partner original (el que escribió por WhatsApp)
        original = Partner.browse(partner_id)
        if not original.exists():
            raise ValueError(f"Partner {partner_id} no existe")

        memory = Memory.get_or_create(original)

        contact_name = data['contact_name']
        company_name = data.get('company_name') or contact_name
        rubro_cat_id = data['rubro_partner_category_id']
        necesita_factura = bool(data.get('necesita_factura'))
        rol = data['rol']
        street = data['street']
        city = data['city']
        disponibilidad = data['disponibilidad']
        notas_extra = data.get('notas_extra') or ''

        # ─── 1. Crear o actualizar EMPRESA ───
        if necesita_factura:
            fiscal_name = data['fiscal_name']
            vat = data['vat'].strip()

            # Buscar por CUIT primero (más confiable que name)
            company = Partner.search([
                ('vat', '=', vat),
                ('is_company', '=', True),
            ], limit=1)
            if not company:
                # Por name similar
                company = Partner.search([
                    ('name', 'ilike', fiscal_name),
                    ('is_company', '=', True),
                ], limit=1)

            company_vals = {
                'street': street,
                'city': city,
                'state_id': STATE_CORDOBA,
                'country_id': COUNTRY_AR,
                'property_product_pricelist': PRICELIST_LE2,
                'category_id': [(4, CATEGORY_EMPRESA), (4, rubro_cat_id)],
            }

            if company:
                # Actualizar solo campos vacíos para no pisar datos buenos
                update_vals = {'category_id': [(4, CATEGORY_EMPRESA), (4, rubro_cat_id)]}
                for k in ('street', 'city'):
                    if not company[k]:
                        update_vals[k] = company_vals[k]
                if not company.property_product_pricelist:
                    update_vals['property_product_pricelist'] = PRICELIST_LE2
                if not company.state_id:
                    update_vals['state_id'] = STATE_CORDOBA
                if not company.country_id:
                    update_vals['country_id'] = COUNTRY_AR
                company.write(update_vals)
                _logger.info("🏢 Empresa actualizada: %s (id=%s)", company.name, company.id)
            else:
                company_vals.update({
                    'name': fiscal_name,
                    'vat': vat,
                    'is_company': True,
                    'company_type': 'company',
                })
                company = Partner.create(company_vals)
                _logger.info("🏢 Empresa creada: %s (id=%s)", company.name, company.id)

            # ─── 2. SUBCONTACTO bajo la empresa ───
            # Si el partner original ya tiene parent_id distinto, NO lo movemos
            # (puede ser un Mario que también compra para otra empresa).
            # Buscamos un subcontacto que coincida con el mobile.
            mobile = original.mobile or original.phone or ''
            existing_subcontact = Partner.search([
                ('parent_id', '=', company.id),
                '|',
                ('mobile', '=', mobile),
                ('phone', '=', mobile),
            ], limit=1)

            if existing_subcontact:
                contact = existing_subcontact
                contact.write({
                    'function': contact.function or rol,
                    'name': contact.name if contact.name and contact.name != company.name else contact_name,
                })
                _logger.info("👤 Subcontacto existente actualizado: %s", contact.name)
            elif not original.parent_id and not original.is_company:
                # Mover al partner original como subcontacto de la empresa
                original.write({
                    'parent_id': company.id,
                    'name': contact_name,
                    'function': rol,
                    'type': 'contact',
                })
                contact = original
                _logger.info("👤 Partner original convertido en subcontacto: %s", contact.name)
            else:
                # Crear nuevo subcontacto (caso: Mario tiene parent_id otro, escribe por Tortugas)
                contact = Partner.create({
                    'name': contact_name,
                    'parent_id': company.id,
                    'function': rol,
                    'mobile': mobile,
                    'phone': mobile,
                    'type': 'contact',
                })
                _logger.info("👤 Subcontacto nuevo creado: %s", contact.name)

            partner_for_lead = company

        else:
            # Sin factura: usamos el partner original directamente
            original.write({
                'name': contact_name,
                'function': rol,
                'street': street,
                'city': city,
                'state_id': original.state_id.id or STATE_CORDOBA,
                'country_id': original.country_id.id or COUNTRY_AR,
                'property_product_pricelist': original.property_product_pricelist.id or PRICELIST_LE2,
                'category_id': [(4, CATEGORY_EMPRESA), (4, rubro_cat_id)],
            })
            partner_for_lead = original
            contact = original
            company = None
            _logger.info("👤 Sin factura: usando partner original %s", original.name)

        # ─── 3. CREAR LEAD ───
        lead_name = f"[Plan Control] {partner_for_lead.name}"
        lead_description = self._build_lead_description(data, partner_for_lead, contact)

        lead = Lead.create({
            'name': lead_name,
            'partner_id': partner_for_lead.id,
            'contact_name': contact_name,
            'function': rol,
            'mobile': contact.mobile or contact.phone or '',
            'street': street,
            'city': city,
            'team_id': TEAM_VENTAS,
            'stage_id': STAGE_CALIFICADO,
            'user_id': USER_JOACO,
            'type': 'opportunity',
            'description': lead_description,
        })
        _logger.info("📋 Lead creado: %s (id=%s) en stage Calificado", lead.name, lead.id)

        # ─── 4. ACTIVIDAD para Joaco ───
        activity_note = (
            f"<p>Cliente calificado por el chatbot. Solicita relevamiento.</p>"
            f"<p><b>Disponibilidad indicada:</b> {disponibilidad}</p>"
            f"<p><b>Dirección:</b> {street}, {city}</p>"
            f"<p><b>WhatsApp:</b> {contact.mobile or contact.phone or '-'}</p>"
            f"<p><b>Contacto:</b> {contact_name} ({rol})</p>"
            f"<p>Contactar dentro de las próximas 24hs.</p>"
        )
        activity = Activity.create({
            'res_model': 'crm.lead',
            'res_model_id': env['ir.model']._get('crm.lead').id,
            'res_id': lead.id,
            'activity_type_id': ACTIVITY_VISITAR_INSTITUCION,
            'summary': f"[CALIFICADO] Coordinar relevamiento con {partner_for_lead.name}",
            'note': activity_note,
            'date_deadline': date.today(),
            'user_id': USER_JOACO,
        })
        _logger.info("📅 Actividad creada (id=%s) para Joaco", activity.id)

        # ─── 5. ACTUALIZAR MEMORY ───
        memory.write({
            'lead_id': lead.id,
            'qual_qualified': True,
            'flow_state': 'inst_handed_over',
            'client_type': 'institucional',
            'human_takeover': True,
            'takeover_until': False,  # indefinido
            'takeover_reason': 'Calificación institucional completada',
            'qualification_data': {},  # limpieza
        })
        _logger.info("🤫 Memory actualizada — takeover activado para %s", contact.name)

        return {
            "ok": True,
            "lead_id": lead.id,
            "lead_name": lead.name,
            "lead_stage": "Calificado (id=14)",
            "partner_id": partner_for_lead.id,
            "partner_name": partner_for_lead.name,
            "contact_id": contact.id,
            "contact_name": contact.name,
            "activity_id": activity.id,
            "takeover_activated": True,
            "summary_for_client": (
                f"🏢 {partner_for_lead.name}\n"
                f"👤 {contact_name} ({rol})\n"
                f"📍 {street}, {city}\n"
                f"🗓️ Disponibilidad: {disponibilidad}"
            ),
            "message": (
                "Calificación completada exitosamente. Mandá el mensaje de "
                "cierre al cliente con el resumen. A partir de ahora el "
                "takeover está activo y no procesás más mensajes de este "
                "cliente — Joaco se encarga manualmente."
            ),
        }

    def _build_lead_description(self, data, partner_for_lead, contact):
        from odoo import fields as _f
        return f"""Calificación automática del chatbot — Plan Control institucional.

Rubro: {data.get('rubro_label', '')}
Empresa: {partner_for_lead.name}
CUIT: {partner_for_lead.vat or '(no informado)'}
Necesita factura: {'Sí' if data.get('necesita_factura') else 'No'}
Contacto: {data.get('contact_name', '')} - {data.get('rol', '')}
Teléfono: {contact.mobile or contact.phone or '-'}
Dirección: {data.get('street', '')}, {data.get('city', '')}
Disponibilidad: {data.get('disponibilidad', '')}

--- Notas adicionales del cliente ---
{data.get('notas_extra') or '(sin notas adicionales)'}

Calificado el: {_f.Datetime.now()}
"""
