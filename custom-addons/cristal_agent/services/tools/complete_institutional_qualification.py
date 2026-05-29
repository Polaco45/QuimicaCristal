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
ACTIVITY_COORDINAR_VISITA = 2   # "Llamada" — usar para coordinar visita Plan Control. Si Joaco crea un type "Coordinar visita" propio, cambiar este ID.
CATEGORY_EMPRESA = 1
IDENTIFICATION_TYPE_CUIT = 4   # l10n_latam.identification.type CUIT

# Stages CERRADOS de crm.lead (no reusamos opportunities en estos)
# 4 = Ganado, 13 = Perdido
STAGES_CLOSED = (4, 13)

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


def _sanitize_vat(vat):
    """Quita guiones, espacios y puntos del CUIT. Devuelve solo dígitos."""
    if not vat:
        return ''
    import re
    return re.sub(r'\D', '', vat)


def _resolve_rubro_category_id(env, rubro_label, rubro_category_id):
    """
    Resuelve el ID de partner.category del rubro.

    Si `rubro_category_id` viene válido (>0), lo usa directamente.
    Si viene 0/None/False pero hay `rubro_label`, busca en res.partner.category
    bajo el parent_id=14 (Rubros) por nombre case-insensitive y devuelve el
    primer match razonable.

    Devuelve int (ID) o None si no se pudo resolver.
    """
    # Caso A: ya viene un ID válido > 0
    if rubro_category_id and isinstance(rubro_category_id, int) and rubro_category_id > 0:
        cat = env['res.partner.category'].sudo().browse(rubro_category_id)
        if cat.exists():
            return rubro_category_id

    # Caso B: hay que resolver por nombre
    if not rubro_label or not isinstance(rubro_label, str):
        return None

    label_norm = rubro_label.strip().lower()
    if not label_norm:
        return None

    Cat = env['res.partner.category'].sudo()
    # Primero búsqueda exacta bajo parent Rubros (id=14)
    found = Cat.search([
        ('parent_id', '=', 14),
        ('name', '=ilike', label_norm),
    ], limit=1)
    if found:
        return found.id

    # Búsqueda parcial bajo parent Rubros
    found = Cat.search([
        ('parent_id', '=', 14),
        ('name', 'ilike', label_norm),
    ], limit=1)
    if found:
        return found.id

    # Búsqueda inversa: el label contiene el nombre de la categoría
    # (ej: label="agricola y agro" matchea "Agro")
    all_rubros = Cat.search([('parent_id', '=', 14)])
    for cat in all_rubros:
        if cat.name and cat.name.lower() in label_norm:
            return cat.id

    return None


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
                    "rubro_label (str), rubro_partner_category_id (int, opcional: si lo dejás en 0 o no lo pasás, la tool lo resuelve buscando por rubro_label en partner.category), "
                    "email (str, obligatorio para mandar cotización después), "
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
                    "email": {"type": "string"},
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
                    "contact_name", "company_name", "rubro_label",
                    "email",
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

        # ─── Resolver rubro por nombre si vino 0/None ───
        # FIX v1.9.6: la tool ahora resuelve sola el ID de partner.category
        # cuando el bot pasa rubro_partner_category_id=0 (caso AGRO 2000).
        resolved_rubro_id = _resolve_rubro_category_id(
            env,
            data.get('rubro_label'),
            data.get('rubro_partner_category_id'),
        )
        if resolved_rubro_id:
            data['rubro_partner_category_id'] = resolved_rubro_id
        else:
            # Si el rubro no se pudo resolver, no abortamos: usamos solo la
            # categoría EMPRESA (1) en el partner y dejamos rubro_cat_id=None
            # para que en el bloque atómico no se intente hacer (4, None).
            data['rubro_partner_category_id'] = None
            _logger.warning(
                "⚠️ Rubro no resuelto para label '%s'. Partner queda sin rubro_cat_id.",
                data.get('rubro_label'),
            )

        # ── Validaciones previas (antes de la transacción) ──
        required = ['contact_name', 'company_name', 'rubro_label', 'email',
                    'rol', 'street', 'city', 'disponibilidad']
        missing = [k for k in required if not data.get(k)]
        if missing:
            return {
                "ok": False,
                "error": f"Faltan datos: {', '.join(missing)}",
                "missing": missing,
            }

        # Validación rápida formato email
        email = (data.get('email') or '').strip().lower()
        if '@' not in email or '.' not in email.split('@')[-1]:
            return {
                "ok": False,
                "error": f"Email inválido: '{email}'. Volvé a preguntar el correo electrónico.",
                "missing": ['email'],
            }
        data['email'] = email

        # Validar zona ANTES de hacer cualquier escritura
        city_norm = _normalize_city(data.get('city', ''))
        if city_norm not in VALID_CITIES_NORMALIZED:
            # Fuera de zona — marcar memory y NO crear nada
            partner = env['res.partner'].sudo().browse(partner_id)
            if partner.exists():
                memory = env['cristal.agent.memory'].sudo().get_or_create(partner)
                memory.write({
                    'flow_state': 'inst_out_of_zone',
                    'qualification_data': data,
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
        try:
            with env.cr.savepoint():
                result = self._do_atomic_close(env, partner_id, data)
            return result
        except Exception as e:
            _logger.exception("Error en cierre atómico institucional: %s", e)
            # FIX v1.9.6: si falla el cierre, SIEMPRE activamos takeover
            # para que el bot deje de contestar y Joaco intervenga manualmente.
            try:
                partner = env['res.partner'].sudo().browse(partner_id)
                if partner.exists():
                    memory = env['cristal.agent.memory'].sudo().get_or_create(partner)
                    memory.write({
                        'human_takeover': True,
                        'takeover_reason': f"Cierre atómico falló: {str(e)[:200]}",
                    })
                    _logger.info("🤫 Takeover activado por error de cierre")
            except Exception as e2:
                _logger.error("No se pudo activar takeover tras error: %s", e2)
            return {
                "ok": False,
                "error": f"Falló cierre atómico (rollback hecho, takeover activado): {str(e)[:200]}",
                "rollback": True,
                "takeover_set": True,
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
        rubro_cat_id = data.get('rubro_partner_category_id')  # puede ser None si no resolvió
        email = data.get('email')
        necesita_factura = bool(data.get('necesita_factura'))
        rol = data['rol']
        street = data['street']
        city = data['city']

        # Helper para construir lista de categorías
        # (siempre EMPRESA, + rubro si se resolvió)
        def _cat_ids():
            base = [(4, CATEGORY_EMPRESA)]
            if rubro_cat_id:
                base.append((4, rubro_cat_id))
            return base
        disponibilidad = data['disponibilidad']
        notas_extra = data.get('notas_extra') or ''

        # ─── 1. Crear o actualizar EMPRESA ───
        if necesita_factura:
            fiscal_name = data['fiscal_name']
            vat_raw = data['vat'].strip()
            vat = _sanitize_vat(vat_raw)   # quita guiones, espacios, puntos

            if not vat or len(vat) != 11:
                raise ValueError(
                    f"CUIT inválido: '{vat_raw}'. Debe tener 11 dígitos. "
                    f"Después de sanitizar quedó '{vat}' ({len(vat)} dígitos)."
                )

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
                'category_id': _cat_ids(),
            }

            if company:
                # Actualizar solo campos vacíos para no pisar datos buenos
                update_vals = {
                    'category_id': _cat_ids(),
                    # Pricelist L.E 2 SIEMPRE en institucional, aunque la
                    # empresa ya tuviera otra cargada (regla del brief).
                    'property_product_pricelist': PRICELIST_LE2,
                }
                for k in ('street', 'city'):
                    if not company[k]:
                        update_vals[k] = company_vals[k]
                if not company.state_id:
                    update_vals['state_id'] = STATE_CORDOBA
                if not company.country_id:
                    update_vals['country_id'] = COUNTRY_AR
                # Si no tenía tipo de identificación seteado, ponemos CUIT
                if not company.l10n_latam_identification_type_id:
                    update_vals['l10n_latam_identification_type_id'] = IDENTIFICATION_TYPE_CUIT
                company.write(update_vals)
                _logger.info("🏢 Empresa actualizada: %s (id=%s)", company.name, company.id)
            else:
                company_vals.update({
                    'name': fiscal_name,
                    # IMPORTANTE: setear el tipo de identificación ANTES del vat
                    # para que el validador de l10n_ar use CUIT (no DNI default)
                    'l10n_latam_identification_type_id': IDENTIFICATION_TYPE_CUIT,
                    'vat': vat,
                    'is_company': True,
                    'company_type': 'company',
                })
                company = Partner.create(company_vals)
                _logger.info("🏢 Empresa creada: %s (id=%s, vat=%s)", company.name, company.id, vat)

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
                    'email': contact.email or email,
                })
                _logger.info("👤 Subcontacto existente actualizado: %s", contact.name)
            elif not original.parent_id and not original.is_company:
                # Mover al partner original como subcontacto de la empresa
                original.write({
                    'parent_id': company.id,
                    'name': contact_name,
                    'function': rol,
                    'type': 'contact',
                    'email': email,
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
                    'email': email,
                    'type': 'contact',
                })
                _logger.info("👤 Subcontacto nuevo creado: %s", contact.name)

            # Email también en la empresa si no tenía
            if email and not company.email:
                company.write({'email': email})

            partner_for_lead = company

        else:
            # ═══════════════════════════════════════════════════════════
            # FIX v1.9.7: Sin factura tambi\u00e9n debe crear empresa madre.
            # La empresa existe en la realidad aunque no haya CUIT —
            # tiene que estar como partner is_company=True para que las
            # cotizaciones, mails y actividades futuras se hagan contra ella.
            # ═══════════════════════════════════════════════════════════
            if company_name and company_name.strip() and company_name.strip().lower() != contact_name.strip().lower():
                # Buscar si la empresa ya existe por nombre (sin CUIT no hay otra forma)
                company = Partner.search([
                    ('name', '=ilike', company_name.strip()),
                    ('is_company', '=', True),
                ], limit=1)
                if not company:
                    company = Partner.search([
                        ('name', 'ilike', company_name.strip()),
                        ('is_company', '=', True),
                    ], limit=1)

                company_vals = {
                    'street': street,
                    'city': city,
                    'state_id': STATE_CORDOBA,
                    'country_id': COUNTRY_AR,
                    'email': email,
                    'property_product_pricelist': PRICELIST_LE2,
                    'category_id': _cat_ids(),
                }

                if company:
                    update_vals = {
                        'category_id': _cat_ids(),
                        'property_product_pricelist': PRICELIST_LE2,
                    }
                    for k in ('street', 'city'):
                        if not company[k]:
                            update_vals[k] = company_vals[k]
                    if not company.state_id:
                        update_vals['state_id'] = STATE_CORDOBA
                    if not company.country_id:
                        update_vals['country_id'] = COUNTRY_AR
                    if email and not company.email:
                        update_vals['email'] = email
                    company.write(update_vals)
                    _logger.info("🏢 Empresa (sin factura) actualizada: %s (id=%s)", company.name, company.id)
                else:
                    company_vals.update({
                        'name': company_name.strip(),
                        'is_company': True,
                        'company_type': 'company',
                    })
                    company = Partner.create(company_vals)
                    _logger.info("🏢 Empresa (sin factura) creada: %s (id=%s)", company.name, company.id)

                # Subcontacto Lucas Pérez bajo Frigorífico San Juan
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
                        'email': contact.email or email,
                    })
                    _logger.info("👤 Subcontacto existente: %s", contact.name)
                elif not original.parent_id and not original.is_company:
                    # Mover al partner original como subcontacto
                    original.write({
                        'parent_id': company.id,
                        'name': contact_name,
                        'function': rol,
                        'type': 'contact',
                        'email': email,
                        # Importante: NO setear category_id acá. Las categorías
                        # van en la empresa, no en el contacto.
                        'category_id': [(5, 0, 0)],  # vacía categorías del contacto
                    })
                    contact = original
                    _logger.info("👤 Original → subcontacto: %s bajo %s", contact.name, company.name)
                else:
                    # Original tiene parent_id distinto: crear subcontacto nuevo
                    contact = Partner.create({
                        'name': contact_name,
                        'parent_id': company.id,
                        'function': rol,
                        'mobile': mobile,
                        'phone': mobile,
                        'email': email,
                        'type': 'contact',
                    })
                    _logger.info("👤 Subcontacto nuevo (sin factura): %s", contact.name)

                partner_for_lead = company

            else:
                # company_name vacío o igual al contact_name: realmente no hay
                # empresa que crear (ej: monotributista que se llama igual).
                # Usamos al partner original como is_company=True (vendedor independiente).
                original.write({
                    'name': contact_name,
                    'function': rol,
                    'street': street,
                    'city': city,
                    'email': email,
                    'state_id': original.state_id.id or STATE_CORDOBA,
                    'country_id': original.country_id.id or COUNTRY_AR,
                    'property_product_pricelist': PRICELIST_LE2,
                    'category_id': _cat_ids(),
                })
                partner_for_lead = original
                contact = original
                company = None
                _logger.info("👤 Sin empresa separada (monotributo/individual): %s", original.name)

        # ─── 3. CREAR/REUSAR OPORTUNIDAD ───
        # FIX v1.9.6: ya no creamos lead — siempre opportunity.
        # Si ya hay una opp abierta del partner (no Ganada/Perdida), la reusamos.
        opp_name = f"[Plan Control] {partner_for_lead.name}"
        opp_description = self._build_lead_description(data, partner_for_lead, contact)

        existing_opp = Lead.search([
            ('partner_id', '=', partner_for_lead.id),
            ('type', '=', 'opportunity'),
            ('stage_id', 'not in', list(STAGES_CLOSED)),
            ('active', '=', True),
        ], order='create_date desc', limit=1)

        if existing_opp:
            # Actualizar la existente — la "ascendemos" a Calificado
            update_vals = {
                'stage_id': STAGE_CALIFICADO,
                'user_id': USER_JOACO,
                'team_id': TEAM_VENTAS,
                'contact_name': contact_name,
                'function': rol,
                'street': street,
                'city': city,
                'email_from': data.get('email') or existing_opp.email_from,
                'mobile': contact.mobile or contact.phone or existing_opp.mobile,
            }
            existing_opp.write(update_vals)
            # Agregar la descripción nueva al final de la existente
            prev = existing_opp.description or ''
            existing_opp.write({
                'description': (
                    f"{prev}\n\n=== RECALIFICACIÓN {date.today().isoformat()} ===\n{opp_description}"
                    if prev else opp_description
                ),
            })
            opp = existing_opp
            _logger.info("📋 Oportunidad EXISTENTE reusada: %s (id=%s) → stage Calificado", opp.name, opp.id)
        else:
            opp = Lead.create({
                'name': opp_name,
                'partner_id': partner_for_lead.id,
                'contact_name': contact_name,
                'function': rol,
                'mobile': contact.mobile or contact.phone or '',
                'email_from': data.get('email'),
                'street': street,
                'city': city,
                'team_id': TEAM_VENTAS,
                'stage_id': STAGE_CALIFICADO,
                'user_id': USER_JOACO,
                'type': 'opportunity',
                'description': opp_description,
            })
            _logger.info("📋 Oportunidad CREADA: %s (id=%s) en stage Calificado", opp.name, opp.id)

        # Mantener `lead` como alias para no romper el resto del código
        lead = opp

        # ─── 4. ACTIVIDAD "Coordinar visita" para Joaco HOY ───
        # FIX v1.9.6: cambia de "Visitar Institucion (3, +1d)" a "Llamada (2, hoy)"
        # con summary explícito. La coordinación se hace HOY por tel/whatsapp,
        # la visita real es otro día (Joaco la agenda manualmente después).
        activity_note = (
            f"<p><b>🎯 Coordinar visita Plan Control — {partner_for_lead.name}</b></p>"
            f"<p>Cliente calificado por el chatbot. Llamarlo/WhatsAppearlo HOY para coordinar día y horario de visita.</p>"
            f"<p><b>Disponibilidad que indicó:</b> {disponibilidad}</p>"
            f"<p><b>Dirección:</b> {street}, {city}</p>"
            f"<p><b>WhatsApp:</b> {contact.mobile or contact.phone or '-'}</p>"
            f"<p><b>Email:</b> {data.get('email') or '-'}</p>"
            f"<p><b>Contacto:</b> {contact_name} ({rol})</p>"
        )
        activity = Activity.create({
            'res_model': 'crm.lead',
            'res_model_id': env['ir.model']._get('crm.lead').id,
            'res_id': opp.id,
            'activity_type_id': ACTIVITY_COORDINAR_VISITA,
            'summary': f"Coordinar visita Plan Control: {partner_for_lead.name}",
            'note': activity_note,
            'date_deadline': date.today(),   # HOY, no +1d
            'user_id': USER_JOACO,
        })
        _logger.info("📞 Actividad 'Coordinar visita' creada (id=%s) para Joaco — deadline HOY", activity.id)

        # ─── 5. ACTUALIZAR MEMORY ───
        memory.write({
            'lead_id': opp.id,
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
            "lead_id": opp.id,
            "opportunity_id": opp.id,
            "lead_name": opp.name,
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
Email: {data.get('email', '-')}
Teléfono: {contact.mobile or contact.phone or '-'}
Dirección: {data.get('street', '')}, {data.get('city', '')}
Disponibilidad: {data.get('disponibilidad', '')}

--- Notas adicionales del cliente ---
{data.get('notas_extra') or '(sin notas adicionales)'}

Calificado el: {_f.Datetime.now()}
"""
