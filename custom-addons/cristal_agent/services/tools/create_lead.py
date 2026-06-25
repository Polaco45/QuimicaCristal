# -*- coding: utf-8 -*-
"""
Tool: create_lead

Crea un lead en CRM. Al crearlo, se aplican defaults según el tipo de cliente:
- Mayorista: user_id=Claudio (id 721), team_id=Cristal Mayorista (5)
- Empresa: user_id=Joaco (id 18), team_id=Ventas (1)
- CF: NO se crea lead

PROTECCIÓN ANTI-DUPLICACIÓN:
Si el partner YA tiene un lead activo (no won, no lost) gestionado por el agente,
NO crea uno nuevo. Devuelve el existente y actualiza sus datos si corresponde.
"""
import json
import logging
from datetime import date
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class CreateLead(AgentTool):
    name = "create_lead"
    description = (
        "Crea un lead nuevo en CRM para un cliente. Se asigna automáticamente al "
        "vendedor correcto según el tipo: mayoristas → Claudio (yo), empresas → Joaco. "
        "Se crea una actividad inicial 'Iniciativa de venta'. "
        "IMPORTANTE: si el partner YA tiene un lead activo gestionado por mí, "
        "esta tool devuelve el lead existente (NO crea otro). Esto evita duplicados. "
        "Pasale qualification_data si tenés las respuestas de la calificación."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {
                "type": "integer",
                "description": "ID del partner cliente.",
            },
            "lead_name": {
                "type": "string",
                "description": "Título del lead. Ej: 'Pedido Whatsapp: María Pérez'.",
            },
            "client_type": {
                "type": "string",
                "enum": ["mayorista", "empresa"],
                "description": "mayorista o empresa (CF NO crea lead).",
            },
            "phase": {
                "type": "string",
                "enum": ["phase_1", "phase_2", "phase_3", "phase_4", "phase_5"],
                "description": "Fase comercial. Default: phase_1.",
            },
            "expected_revenue": {
                "type": "number",
                "description": "Revenue esperado del lead (opcional).",
            },
            "qualification_data": {
                "type": "object",
                "description": "Datos de la calificación (opcional).",
            },
            "description": {
                "type": "string",
                "description": "Descripción libre del lead.",
            },
            "contact_name": {
                "type": "string",
                "description": "Nombre real de la PERSONA que escribe (ej: 'Carla'). "
                               "Se graba en el lead y, si el contacto es nuevo, "
                               "reemplaza el nombre que trajo el perfil de WhatsApp.",
            },
            "company_name": {
                "type": "string",
                "description": "Nombre real de la EMPRESA/local (ej: 'Resto la Liendre').",
            },
        },
        "required": ["partner_id", "lead_name", "client_type"],
    }

    def _execute(self, env, run=None, partner_id=None, lead_name=None,
                 client_type=None, phase='phase_1', expected_revenue=None,
                 qualification_data=None, description=None,
                 contact_name=None, company_name=None, **kwargs):
        if not (partner_id and lead_name and client_type):
            return {"error": "partner_id, lead_name y client_type son obligatorios"}

        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        # v1.10.4 — Si el contacto es FRESCO (autocreado por WhatsApp: sin email,
        # sin empresa padre, no es company), su nombre vino del perfil de WhatsApp
        # o es un placeholder. Lo pisamos con el nombre real capturado en la charla
        # para no dejar el contacto mal etiquetado (ej. "Química Cristal").
        if contact_name and not partner.is_company and not partner.parent_id and not partner.email:
            if partner.name != contact_name:
                partner.write({'name': contact_name})

        # ═════════════════ PROTECCIÓN ANTI-DUPLICADO ═════════════════
        # Buscar lead activo existente gestionado por el agente
        Lead = env['crm.lead'].sudo()
        existing_domain = [
            ('partner_id', '=', partner.id),
            ('agent_managed', '=', True),
            ('active', '=', True),
        ]
        # Excluir leads ganados o perdidos
        existing_leads = Lead.search(existing_domain, order='create_date desc')
        # Filtramos los que NO estén en stage won/lost
        existing_active = existing_leads.filtered(
            lambda l: not (l.stage_id and l.stage_id.is_won) and l.probability < 100 and l.active
        )

        if existing_active:
            lead = existing_active[0]
            _logger.info(
                "🔁 create_lead: ya existe lead activo %s para partner %s. NO creo otro.",
                lead.id, partner.name
            )

            # Actualizar datos del existente con nueva info si corresponde
            update_vals = {}
            if phase and lead.agent_strategy_phase != phase:
                update_vals['agent_strategy_phase'] = phase
            if expected_revenue is not None and not lead.expected_revenue:
                update_vals['expected_revenue'] = float(expected_revenue)
            if qualification_data:
                # Mergear datos de calificación
                try:
                    existing_data = json.loads(lead.agent_qualification_data or '{}')
                except (json.JSONDecodeError, TypeError):
                    existing_data = {}
                existing_data.update(qualification_data)
                update_vals['agent_qualification_data'] = json.dumps(existing_data, ensure_ascii=False)
            if description and not lead.description:
                update_vals['description'] = description
            # v1.10.4 — completar contacto/empresa reales si faltaban
            if contact_name and not lead.contact_name:
                update_vals['contact_name'] = contact_name
            if company_name and not lead.partner_name:
                update_vals['partner_name'] = company_name
            if update_vals:
                lead.write(update_vals)

            return {
                "ok": True,
                "lead_id": lead.id,
                "lead_name": lead.name,
                "is_existing": True,  # señal de que es uno preexistente, no nuevo
                "user_assigned": lead.user_id.name if lead.user_id else '',
                "team": lead.team_id.name if lead.team_id else '',
                "summary": (
                    f"⚠️ Ya existía un lead activo para {partner.name} "
                    f"(id={lead.id}, {lead.name}). Lo actualicé en vez de crear duplicado."
                ),
            }
        # ════════════════════════════════════════════════════════════════

        config = env['cristal.agent.config'].sudo().get_active()

        # Resolver user y team según tipo
        if client_type == 'mayorista':
            user_id = config.bot_user_id.id if config.bot_user_id else 1
            team = env['crm.team'].sudo().search([('name', '=', 'Cristal Mayorista')], limit=1)
            team_id = team.id if team else False
        elif client_type == 'empresa':
            user_id = config.owner_user_id.id if config.owner_user_id else 18
            team = env['crm.team'].sudo().search([('name', '=', 'Ventas')], limit=1)
            team_id = team.id if team else False
        else:
            return {"error": f"client_type inválido: {client_type}"}

        # Vals del opp (FIX v1.9.6: forzar type=opportunity, nunca lead)
        vals = {
            'name': lead_name,
            'partner_id': partner.id,
            'user_id': user_id,
            'team_id': team_id,
            'type': 'opportunity',
            'agent_managed': True,
            'agent_strategy_phase': phase,
        }
        if expected_revenue is not None:
            vals['expected_revenue'] = float(expected_revenue)
        if qualification_data:
            vals['agent_qualification_data'] = json.dumps(qualification_data, ensure_ascii=False)
        if description:
            vals['description'] = description
        # v1.10.4 — grabar contacto y empresa reales en el lead, en vez de dejar
        # que Odoo los autocomplete desde el nombre (a veces sucio) del partner.
        if contact_name:
            vals['contact_name'] = contact_name
        if company_name:
            vals['partner_name'] = company_name

        try:
            lead = Lead.create(vals)
        except Exception as e:
            _logger.exception("Error creando lead: %s", e)
            return {"error": f"No se pudo crear el lead: {e}"}

        # Crear actividad inicial "Iniciativa de venta"
        activity_type = env['mail.activity.type'].sudo().search(
            [('name', '=', 'Iniciativa de venta')], limit=1
        )
        if not activity_type:
            # Fallback: usar id 4 (Actividades pendientes según el system prompt)
            activity_type = env['mail.activity.type'].sudo().browse(4)

        if activity_type.exists():
            try:
                env['mail.activity'].sudo().create({
                    'res_model': 'crm.lead',
                    'res_model_id': env['ir.model']._get_id('crm.lead'),
                    'res_id': lead.id,
                    'activity_type_id': activity_type.id,
                    'user_id': user_id,
                    'date_deadline': date.today(),
                    'summary': f"Seguimiento {client_type} — {lead_name}",
                })
            except Exception as e:
                _logger.warning("No se pudo crear actividad inicial: %s", e)

        # Vincular memory con lead
        memory = env['cristal.agent.memory'].sudo().search(
            [('partner_id', '=', partner.id)], limit=1
        )
        if memory:
            memory.write({'lead_id': lead.id})

        # Actualizar fase del partner
        partner_phase_map = {
            'phase_1': 'phase_1_qualifying',
            'phase_2': 'phase_2_post_sample',
            'phase_3': 'phase_3_onboarding',
            'phase_4': 'phase_4_active_customer',
            'phase_5': 'phase_5_loyalty',
        }
        if phase in partner_phase_map:
            partner.write({'agent_strategy_phase': partner_phase_map[phase]})

        return {
            "ok": True,
            "lead_id": lead.id,
            "lead_name": lead.name,
            "is_existing": False,
            "user_assigned": lead.user_id.name if lead.user_id else '',
            "team": lead.team_id.name if lead.team_id else '',
            "summary": f"Lead creado: {lead.name} (id={lead.id}), asignado a {lead.user_id.name}",
        }
