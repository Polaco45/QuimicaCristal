# -*- coding: utf-8 -*-
"""
Tool: escalate_to_joaco

Postea un mensaje en el canal interno Joaco↔Claudio (id 969 por default)
mencionando a Joaco para que se entere de algo que necesita su atención.

Usar SIEMPRE cuando:
- Hay un reclamo o queja del cliente
- Llega un audio (no podemos procesar audios todavía)
- Cliente pide algo que requiere decisión de Joaco (descuento, plazo, cuenta corriente)
- Cliente cita a Joaco ("Joaco me dijo X")
- Cliente nuevo es Empresa
- Detectaste duplicados de número en la base
- Algo no entendiste y no querés inventar

El mensaje al canal interno debe ser CONCISO: contexto + qué pasó + qué necesitás de él.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class EscalateToJoaco(AgentTool):
    name = "escalate_to_joaco"
    description = (
        "Postea un mensaje en el canal interno con Joaco para escalarle algo. "
        "Lo usa cuando algo necesita su atención. El mensaje debe ser conciso: "
        "qué pasó + qué cliente está involucrado + qué decisión/acción necesitás de él. "
        "Si querés mencionar el partner, podés pasarle related_partner_id y el mensaje "
        "incluye el link al cliente automáticamente."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Mensaje a postear. HTML permitido. Conciso, contextual.",
            },
            "related_partner_id": {
                "type": "integer",
                "description": "ID del partner involucrado (opcional, se incluye link al final).",
            },
            "urgency": {
                "type": "string",
                "enum": ["normal", "alta"],
                "description": "Si es 'alta', se agrega un 🚨 al inicio del mensaje.",
                "default": "normal",
            },
        },
        "required": ["message"],
    }

    def _execute(self, env, run=None, message=None, related_partner_id=None, urgency='normal', **kwargs):
        if not message:
            return {"error": "message es obligatorio"}

        config = env['cristal.agent.config'].sudo().get_active()
        bot_partner = config.bot_partner_id
        if not bot_partner:
            bot_partner = env['res.partner'].sudo().browse(2)

        owner_partner = config.owner_partner_id
        if not owner_partner:
            owner_partner = env['res.partner'].sudo().browse(65374)

        internal_channel = config.internal_channel_id
        if not internal_channel:
            internal_channel = env['discuss.channel'].sudo().browse(969)

        if not internal_channel.exists():
            return {"error": "Canal interno (id 969 por default) no existe. Configuralo en AgentConfig."}

        # Armar el body
        urgency_prefix = "🚨 " if urgency == 'alta' else ""
        joaco_mention = (
            f'<a href="#" data-oe-id="{owner_partner.id}" data-oe-model="res.partner" '
            f'class="o_mail_redirect">@{owner_partner.name.split()[0] if owner_partner.name else "Joaco"}</a>'
        )

        body = f"<p>{urgency_prefix}{joaco_mention} {message}</p>"

        # Si hay partner relacionado, lo agregamos
        if related_partner_id:
            partner = env['res.partner'].sudo().browse(int(related_partner_id))
            if partner.exists():
                partner_link = (
                    f'<a href="#" data-oe-id="{partner.id}" data-oe-model="res.partner" '
                    f'class="o_mail_redirect">{partner.name}</a>'
                )
                body += f"<p>Cliente: {partner_link} (id={partner.id})</p>"

        # Resolver subtype
        try:
            subtype_id = env.ref('mail.mt_comment').id
        except Exception:
            subtype_id = 1

        # Crear mail.message en el canal interno
        # Usamos mail_notify_force_send=False y mail_create_nolog=True para silenciar
        # el email automático que Odoo manda en cada @mención (cada escalate generaba 1 email).
        try:
            env['mail.message'].sudo().with_context(
                from_cristal_agent=True,
                mail_notify_force_send=False,
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                mail_notify_author=False,
            ).create({
                'author_id': bot_partner.id,
                'body': body,
                'message_type': 'comment',
                'model': 'discuss.channel',
                'res_id': internal_channel.id,
                'subtype_id': subtype_id,
                # NO incluimos partner_ids — eso es lo que dispara el email.
                # Joaco va a ver la mención por el a href en el body cuando entre al canal.
            })
        except Exception as e:
            _logger.exception("Error escalando a Joaco: %s", e)
            return {"error": f"No se pudo escalar: {e}"}

        # Incrementar contador en memory
        if related_partner_id:
            try:
                memory = env['cristal.agent.memory'].sudo().search(
                    [('partner_id', '=', int(related_partner_id))], limit=1
                )
                if memory:
                    memory.increment_escalation()
            except Exception:
                pass

        # v1.22 — además del canal interno (log de respaldo), notificar a Joaco
        # por WhatsApp para que responda desde ahí (canal de operador).
        wa_ok = False
        if getattr(config, 'notify_owner_via_whatsapp', False):
            try:
                wa_ok = self._notify_owner_whatsapp(env, config, message)
            except Exception as e:
                _logger.warning("No se pudo notificar a Joaco por WhatsApp: %s", e)

        return {
            "ok": True,
            "channel_id": internal_channel.id,
            "notified_whatsapp": wa_ok,
            "summary": f"Escalado a Joaco (canal interno{' + WhatsApp' if wa_ok else ''})",
        }

    def _notify_owner_whatsapp(self, env, config, message):
        """Manda la plantilla 'hola_mayorista_crm' al WhatsApp de Joaco con el
        mensaje como texto libre, para que responda desde ahí. Devuelve True si OK."""
        import re as _re
        partner = config.owner_whatsapp_partner_id
        if not partner:
            return False
        txt = _re.sub(r'<[^>]+>', '', message or '').strip()
        if not txt:
            return False
        # El template 'hola_mayorista_crm' tiene 2 variables: {{1}} nombre, {{2}} texto.
        first_name = (partner.name or 'Joaco').split()[0]
        from .send_whatsapp_template import SendWhatsappTemplate
        res = SendWhatsappTemplate()._execute(
            env, partner_id=partner.id, template_name='hola_mayorista_crm',
            variables=[first_name, txt[:900]])
        return bool(res and res.get('ok'))
