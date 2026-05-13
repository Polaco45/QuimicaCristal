# -*- coding: utf-8 -*-
"""
Tool: send_whatsapp_template

Manda un template aprobado de WhatsApp al cliente. Necesario cuando la ventana
de 24hs del cliente está cerrada (el cliente no escribió hace >24hs).

Los templates tienen variables {{1}}, {{2}}, ... que se llenan con texto libre.
Meta aprueba el esqueleto del template, no el contenido de las variables.

Reglas de Meta para variables:
- Texto razonable (no solo URL, no solo emoji, no solo número)
- Longitud razonable (no demasiado largo)
- Coherente con el template aprobado

El bot llama a esta tool cuando:
- send_whatsapp falla porque la ventana está cerrada
- El cron proactivo le pasa una cadencia con template configurado
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class SendWhatsappTemplate(AgentTool):
    name = "send_whatsapp_template"
    description = (
        "Manda un TEMPLATE aprobado de WhatsApp al cliente. Usalo cuando la "
        "ventana de 24hs del cliente está cerrada (es decir, el cliente no "
        "te escribió hace más de un día). Los templates pueden mandarse "
        "EN CUALQUIER MOMENTO, sin importar la ventana. "
        "Las variables son texto libre — vos escribís el contenido de cada {{N}}. "
        "Tipicamente {{1}} es el nombre del cliente. "
        "Lista de templates configurados en cadencias: usá search_knowledge "
        "para ver qué template aplica a cada situación."
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
                "description": "Nombre del template aprobado. Ej: 'oferta_semanal', "
                               "'chequeo_post_muestra'.",
            },
            "variables": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lista de strings para llenar las variables {{1}}, {{2}}, ... "
                               "en orden. Ej: ['Patricia', 'Jabón Extra 200L al precio de 170L']. "
                               "Cada variable debe ser texto razonable — no solo emoji, no solo "
                               "URL, no demasiado largo (Meta puede rechazar).",
            },
            "wa_account_id": {
                "type": "integer",
                "description": "(Opcional) ID de cuenta WhatsApp. Default: la cuenta default "
                               "configurada en el agente.",
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

        if not partner.mobile and not partner.phone:
            return {"error": f"El partner {partner.name} no tiene mobile ni phone"}

        # Buscar template
        WhatsappTemplate = env['whatsapp.template'].sudo()
        template = WhatsappTemplate.search([
            ('name', '=', template_name),
            ('status', '=', 'approved'),
        ], limit=1)

        if not template:
            # Si no encuentra approved, buscar cualquier estado
            template = WhatsappTemplate.search([('name', '=', template_name)], limit=1)
            if not template:
                return {
                    "error": f"No encontré template '{template_name}'. "
                             f"Revisá los nombres disponibles con search_knowledge o "
                             f"pedile a Joaco que cree el template."
                }
            if template.status != 'approved':
                return {
                    "error": f"El template '{template_name}' existe pero no está aprobado "
                             f"por Meta (status: {template.status}). Escalá a Joaco."
                }

        # Resolver cuenta
        if wa_account_id:
            wa_account = env['whatsapp.account'].sudo().browse(int(wa_account_id))
        elif template.wa_account_id:
            wa_account = template.wa_account_id
        else:
            config = env['cristal.agent.config'].sudo().get_active()
            wa_account = getattr(config, 'wa_account_default_id', False)

        if not wa_account or not wa_account.exists():
            return {"error": "No pude determinar la cuenta de WhatsApp para mandar el template"}

        # Normalizar número
        mobile = partner.mobile or partner.phone
        if not mobile.startswith('+'):
            mobile = '+' + mobile.lstrip('0').lstrip()

        # Crear el whatsapp.message con template y variables
        variables = variables or []
        try:
            free_text_json = self._build_free_text_json(template, variables)

            wa_msg = env['whatsapp.message'].sudo().create({
                'wa_account_id': wa_account.id,
                'wa_template_id': template.id,
                'mobile_number': mobile,
                'message_type': 'outbound',
                'state': 'outgoing',
                'free_text_json': free_text_json,
                'mail_message_id': self._create_mail_message(env, partner, template, variables),
            })

            # Mandar inmediatamente si el método existe
            sent_now = False
            try:
                if hasattr(wa_msg, '_send_message'):
                    wa_msg._send_message()
                    sent_now = True
            except Exception as e:
                _logger.warning("_send_message falló, queda en cola: %s", e)

            _logger.info(
                "📤 Template '%s' enviado a %s (%s vars)",
                template_name, partner.name, len(variables)
            )

            return {
                "ok": True,
                "wa_message_id": wa_msg.id,
                "template": template_name,
                "partner": partner.name,
                "mobile": mobile,
                "variables_sent": variables,
                "sent_immediately": sent_now,
                "summary": (
                    f"Template '{template_name}' enviado a {partner.name} "
                    f"con {len(variables)} variables."
                ),
            }

        except Exception as e:
            _logger.exception("Error enviando template: %s", e)
            return {"error": f"No se pudo mandar el template: {e}"}

    def _build_free_text_json(self, template, variables):
        """
        Arma el JSON que el módulo whatsapp espera para las variables.
        Formato esperado por Odoo: {"body": {"1": "valor1", "2": "valor2"}}
        """
        import json
        body = {}
        for i, val in enumerate(variables, start=1):
            body[str(i)] = str(val)
        return json.dumps({"body": body})

    def _create_mail_message(self, env, partner, template, variables):
        """Crea un mail.message para que quede registro del envío en el canal."""
        # Buscar canal del cliente si existe
        Channel = env['discuss.channel'].sudo()
        channel = Channel.search([
            ('channel_type', '=', 'whatsapp'),
            ('whatsapp_partner_id', '=', partner.id),
        ], limit=1) if hasattr(Channel, 'whatsapp_partner_id') else False

        # Renderizar body para preview
        body_html = self._render_template_preview(template, variables)

        config = env['cristal.agent.config'].sudo().get_active()
        bot_partner = config.bot_partner_id or env['res.partner'].sudo().browse(80799)

        msg_vals = {
            'author_id': bot_partner.id,
            'body': body_html,
            'message_type': 'whatsapp_message',
            'subtype_id': env.ref('mail.mt_comment').id,
        }
        if channel:
            msg_vals['model'] = 'discuss.channel'
            msg_vals['res_id'] = channel.id
        else:
            msg_vals['model'] = 'res.partner'
            msg_vals['res_id'] = partner.id

        try:
            msg = env['mail.message'].sudo().with_context(
                from_cristal_agent=True
            ).create(msg_vals)
            return msg.id
        except Exception as e:
            _logger.warning("No se pudo crear mail.message para template: %s", e)
            return False

    def _render_template_preview(self, template, variables):
        """Devuelve HTML con el template renderizado para el preview en mail.message."""
        body = template.body or ""
        for i, val in enumerate(variables, start=1):
            body = body.replace('{{%s}}' % i, str(val))
            body = body.replace('{{ %s }}' % i, str(val))
        return f"<p>[TEMPLATE: {template.name}]</p><p>{body}</p>"
