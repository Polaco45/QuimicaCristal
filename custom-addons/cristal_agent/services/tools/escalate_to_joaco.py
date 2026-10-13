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

        # THROTTLE anti-repetición: si ya se escaló algo PARECIDO al canal interno
        # en las últimas 6 h, no lo repetimos. Joaco se quejó de que el bot le
        # posteaba 3 veces lo mismo y de que cada aviso consumía. La huella son las
        # primeras palabras del mensaje (típicamente el cliente + la acción).
        import re as _re6
        snippet = _re6.sub(r'<[^>]+>', '', message or '').strip()[:45]
        if snippet:
            try:
                from datetime import datetime, timedelta
                dup = env['mail.message'].sudo().search_count([
                    ('model', '=', 'discuss.channel'),
                    ('res_id', '=', internal_channel.id),
                    ('author_id', '=', bot_partner.id),
                    ('create_date', '>=', datetime.now() - timedelta(hours=6)),
                    ('body', 'ilike', snippet),
                ])
                if dup:
                    _logger.info("🔁 Escalación al canal interno OMITIDA (ya se avisó "
                                 "algo igual en las últimas 6h): %s", snippet)
                    return {
                        "ok": True,
                        "throttled": True,
                        "summary": "Ya avisé algo parecido a Joaco hace poco; no lo repetí.",
                    }
            except Exception as e:
                _logger.warning("Throttle de escalación interna falló (sigo y posteo): %s", e)

        # v1.36 — UNA escalación por pedido / por cliente. Caso real: en 4 días hubo 37
        # escalaciones; el pedido de Any (S06359) se escaló 5 veces y el de Santiago
        # Bringas (S06368) 3. Si ya hay un aviso abierto de la misma cotización (72 h)
        # o del mismo cliente (24 h), se ACTUALIZA ese mensaje en vez de crear otro
        # (así también quedan agrupadas las consultas de producto del mismo cliente).
        existing = self._find_open_escalation(env, internal_channel, bot_partner,
                                              message, related_partner_id)
        if existing:
            return self._update_escalation(existing, message, urgency, related_partner_id, env)

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

        # v1.31 — Joaco pidió eliminar el chat por WhatsApp: las escalaciones van
        # SOLO al canal interno de Odoo (concisas y sin repetir). Ya no se le manda
        # nada al WhatsApp de Joaco.
        return {
            "ok": True,
            "channel_id": internal_channel.id,
            "summary": "Escalado a Joaco por el canal interno.",
        }


    # ───────────────────────── v1.36: una escalación por pedido ─────────────────────────
    ORDER_WINDOW_HOURS = 72
    PARTNER_WINDOW_HOURS = 24

    def _find_open_escalation(self, env, channel, bot_partner, message, related_partner_id):
        """Último aviso del bot en el canal interno sobre la MISMA cotización (Sxxxxx)
        o, si no nombra cotización, sobre el mismo cliente."""
        import re as _re
        from datetime import datetime, timedelta
        Msg = env['mail.message'].sudo()
        base = [('model', '=', 'discuss.channel'), ('res_id', '=', channel.id),
                ('author_id', '=', bot_partner.id)]
        plain = _re.sub(r'<[^>]+>', ' ', message or '')
        orders = _re.findall(r'\bS\d{5}\b', plain)
        if orders:
            found = Msg.search(base + [
                ('create_date', '>=', datetime.now() - timedelta(hours=self.ORDER_WINDOW_HOURS)),
                ('body', 'ilike', orders[0]),
            ], order='id desc', limit=1)
            if found:
                return found
        if related_partner_id:
            return Msg.search(base + [
                ('create_date', '>=', datetime.now() - timedelta(hours=self.PARTNER_WINDOW_HOURS)),
                ('body', 'ilike', f"(id={int(related_partner_id)})"),
            ], order='id desc', limit=1)
        return Msg

    def _update_escalation(self, msg, message, urgency, related_partner_id, env):
        """Agrega la novedad al aviso existente (sin crear otro mensaje)."""
        import re as _re
        from ..helpers import now_ar
        new_plain = _re.sub(r'\s+', ' ', _re.sub(r'<[^>]+>', ' ', message or '')).strip()
        old_plain = _re.sub(r'\s+', ' ', _re.sub(r'<[^>]+>', ' ', msg.body or '')).strip()
        if new_plain and new_plain[:120] in old_plain:
            _logger.info("🔁 Escalación repetida (ya estaba en el aviso %s): no la repito.", msg.id)
            return {"ok": True, "throttled": True, "escalation_message_id": msg.id,
                    "summary": "Joaco ya tiene este aviso; no lo repetí."}
        stamp = now_ar(env).strftime('%d/%m %H:%M')
        prefix = "🚨 " if urgency == 'alta' else ""
        msg.with_context(from_cristal_agent=True).write({
            'body': (msg.body or '') + f"<p>{prefix}<b>🔄 Actualización {stamp}:</b> {message}</p>",
        })
        if related_partner_id:
            try:
                memory = env['cristal.agent.memory'].sudo().search(
                    [('partner_id', '=', int(related_partner_id))], limit=1)
                if memory:
                    memory.increment_escalation()
            except Exception:
                pass
        _logger.info("📝 Escalación agregada al aviso existente %s.", msg.id)
        return {"ok": True, "updated_existing": True, "escalation_message_id": msg.id,
                "summary": "Agregué la novedad al aviso que Joaco ya tenía de este "
                           "pedido/cliente (no creé otro mensaje)."}
