# -*- coding: utf-8 -*-
"""
Tool: send_whatsapp_template

Manda un template aprobado de WhatsApp al cliente usando el flujo nativo
de Odoo (whatsapp.composer wizard). Necesario cuando la ventana de 24hs
del cliente está cerrada (el cliente no escribió hace >24hs).

Los templates tienen variables {{1}}, {{2}}, ... Algunas son automáticas
(field_type='field', se llenan del registro como partner.name) y otras
son texto libre (field_type='free_text', se proveen por la tool).

Esta tool SOLO recibe las variables free_text. Las de tipo field se
resuelven automáticamente desde el partner.

Refactor v1.8.3:
- Usa whatsapp.composer en vez de crear whatsapp.message a mano
- Normaliza mobile (saca espacios, guiones)
- Construye free_text_json en el formato correcto que espera Odoo
- Renderiza body limpio (sin prefijo [TEMPLATE: ...])
"""
import logging
import re
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class SendWhatsappTemplate(AgentTool):
    name = "send_whatsapp_template"
    description = (
        "Manda un TEMPLATE aprobado de WhatsApp al cliente. Usalo cuando la "
        "ventana de 24hs del cliente está cerrada (es decir, el cliente no "
        "te escribió hace más de un día). "
        "Solo pasás las variables de texto libre del template — las variables "
        "automáticas (como el nombre del cliente) se completan solas desde "
        "el partner. "
        "Ej: si el template dice 'Hola {{1}}, oferta: {{2}}' donde {{1}} es "
        "auto (nombre) y {{2}} es free_text, pasás variables=['Lavandina 100L pagas 80L']. "
        "Lista de templates configurados: usá search_knowledge."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {
                "type": "integer",
                "description": "ID del partner cliente.",
            },
            "template_name": {
                "type": "string",
                "description": "Nombre del template aprobado. Ej: 'oferta_semanal_general'.",
            },
            "variables": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lista de strings SOLO para las variables free_text del template, "
                               "en el orden en que aparecen. NO incluyas el nombre del cliente "
                               "(eso se llena solo). Cada variable debe ser texto razonable.",
            },
            "wa_account_id": {
                "type": "integer",
                "description": "(Opcional) ID de cuenta WhatsApp. Default: cuenta del template.",
            },
        },
        "required": ["partner_id", "template_name", "variables"],
    }

    def _execute(self, env, run=None, partner_id=None, template_name=None,
                 variables=None, wa_account_id=None, **kwargs):
        if not (partner_id and template_name):
            return {"error": "partner_id y template_name son obligatorios"}

        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        # ─── 1. Mobile bien normalizado ───
        mobile_raw = partner.mobile or partner.phone or ''
        mobile = self._normalize_mobile(mobile_raw)
        if not mobile:
            return {"error": f"Partner {partner.name} no tiene mobile válido"}

        # ─── 2. Template aprobado ───
        WhatsappTemplate = env['whatsapp.template'].sudo()
        template = WhatsappTemplate.search([
            ('name', '=', template_name),
            ('status', '=', 'approved'),
        ], limit=1)

        if not template:
            template = WhatsappTemplate.search([('name', '=', template_name)], limit=1)
            if not template:
                return {
                    "error": f"No encontré template '{template_name}'. "
                             f"Revisá nombres con search_knowledge."
                }
            if template.status != 'approved':
                return {
                    "error": f"Template '{template_name}' existe pero no está aprobado "
                             f"por Meta (status: {template.status}). Escalá a Joaco."
                }

        # ─── 3. Detectar modelo del template y resolver res_id correcto ───
        # Los templates suelen estar configurados sobre crm.lead (con variables
        # tipo partner_id.name). El composer necesita un record de ese modelo
        # para resolver las variables tipo 'field'.
        template_model = template.model_id.model if template.model_id else 'res.partner'
        composer_res_model, composer_res_id, lead_was_created = \
            self._resolve_composer_res(env, template_model, partner, template_name)

        if not composer_res_id:
            return {
                "error": f"No pude determinar registro de {template_model} para "
                         f"el partner {partner.name}. Template no se mandó."
            }

        # ─── 4. Variables como campos free_text_1, free_text_2, ... ───
        # Odoo 18 composer NO usa free_text_json; usa campos char individuales.
        variables = variables or []
        free_text_fields = {}
        for i, val in enumerate(variables, start=1):
            if i <= 10:  # composer soporta hasta free_text_10
                free_text_fields[f'free_text_{i}'] = str(val)

        # ─── 5. Crear composer y enviar ───
        try:
            Composer = env['whatsapp.composer'].sudo()

            composer_vals = {
                'res_model': composer_res_model,
                'res_ids': str(composer_res_id),
                'wa_template_id': template.id,
                'phone': mobile,
                **free_text_fields,
            }

            composer = Composer.with_context(
                active_model=composer_res_model,
                active_ids=[composer_res_id],
                default_res_model=composer_res_model,
                default_res_ids=str(composer_res_id),
            ).create(composer_vals)

            # Enviar usando el método nativo
            send_method = None
            for method_name in [
                'action_send_whatsapp_template',
                '_send_whatsapp_template',
            ]:
                if hasattr(composer, method_name):
                    send_method = getattr(composer, method_name)
                    break

            if not send_method:
                return {
                    "error": "No encontré método de envío en whatsapp.composer. "
                             "Posible cambio de versión Odoo. Escalá a Joaco."
                }

            send_method()

            # Buscar el whatsapp.message creado para confirmar
            wa_msg = env['whatsapp.message'].sudo().search([
                ('wa_template_id', '=', template.id),
                ('mobile_number', 'ilike', mobile[-8:]),
            ], order='create_date desc', limit=1)

            _logger.info(
                "📤 Template '%s' enviado a %s vía composer (model=%s, res_id=%s, %s vars)",
                template_name, partner.name, composer_res_model, composer_res_id, len(variables)
            )

            return {
                "ok": True,
                "wa_message_id": wa_msg.id if wa_msg else None,
                "wa_message_state": wa_msg.state if wa_msg else None,
                "template": template_name,
                "partner": partner.name,
                "mobile": mobile,
                "composer_res_model": composer_res_model,
                "composer_res_id": composer_res_id,
                "lead_auto_created": lead_was_created,
                "variables_sent": variables,
                "summary": (
                    f"Template '{template_name}' enviado a {partner.name} "
                    f"({composer_res_model} id={composer_res_id}) "
                    f"con {len(variables)} variables free_text."
                ),
            }

        except Exception as e:
            _logger.exception("Error enviando template vía composer: %s", e)
            return {"error": f"No se pudo mandar el template: {e}"}

    def _resolve_composer_res(self, env, template_model, partner, template_name):
        """
        Devuelve (res_model, res_id, lead_was_created).
        Si el template usa crm.lead, busca o crea un lead para el partner.
        Si usa res.partner directo, devuelve partner.
        """
        if template_model == 'crm.lead':
            # Buscar lead más reciente del partner
            lead = env['crm.lead'].sudo().search([
                ('partner_id', '=', partner.id),
            ], limit=1, order='create_date desc')

            if lead:
                return 'crm.lead', lead.id, False

            # No hay lead: creamos uno "auto" para que el composer pueda renderizar.
            # Esto pasa típicamente con el broadcast a mayoristas que nunca
            # interactuaron con el bot todavía.
            auto_lead = env['crm.lead'].sudo().create({
                'name': f'[Auto] Envío template {template_name} a {partner.name}',
                'partner_id': partner.id,
                'type': 'lead',
                'description': (
                    f'Lead creado automáticamente para enviar el template '
                    f'"{template_name}" porque el partner no tenía ningún lead '
                    f'previo. Si es un cliente activo, asocialo con su lead real.'
                ),
            })
            _logger.info(
                "🆕 Auto-creé lead %s para %s (necesario para template '%s')",
                auto_lead.id, partner.name, template_name
            )
            return 'crm.lead', auto_lead.id, True

        elif template_model == 'res.partner':
            return 'res.partner', partner.id, False

        else:
            _logger.warning(
                "Template '%s' usa modelo '%s' no soportado por la tool.",
                template_name, template_model
            )
            return None, None, False

    # ────────────── Helpers ──────────────

    def _normalize_mobile(self, raw):
        """Saca espacios, guiones, paréntesis. Deja solo dígitos y +."""
        if not raw:
            return ''
        cleaned = re.sub(r'[^\d+]', '', raw)
        if not cleaned:
            return ''
        if not cleaned.startswith('+'):
            # Si no tiene +, asumimos +54 (Argentina) si arranca con 549
            if cleaned.startswith('549'):
                cleaned = '+' + cleaned
            elif cleaned.startswith('54'):
                cleaned = '+' + cleaned
            else:
                cleaned = '+54' + cleaned.lstrip('0')
        return cleaned

    def _build_free_text_json(self, template, variables):
        """
        Construye el JSON en el formato que espera Odoo:
        {"free_text_1": "valor", "free_text_2": "valor"}

        El índice N se refiere al ORDEN de las variables free_text del template,
        no a la posición {{N}} en el body. Las variables tipo 'field' se llenan
        automáticamente del partner por Odoo.
        """
        if not variables:
            return {}

        # Identificar qué variables del template son free_text
        free_text_vars = template.variable_ids.filtered(
            lambda v: getattr(v, 'field_type', None) == 'free_text'
        ).sorted('name')

        result = {}
        for idx, var in enumerate(free_text_vars, start=1):
            if idx <= len(variables):
                result[f'free_text_{idx}'] = str(variables[idx - 1])

        return result
