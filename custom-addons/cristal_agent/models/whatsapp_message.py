# -*- coding: utf-8 -*-
"""
Hook en whatsapp.message.

Cuando llega un mensaje WhatsApp entrante (state='received' o 'inbound'),
este hook lo intercepta y dispara el agente Claudio.

Reusa la lógica de búsqueda de partner por phone_sanitized del módulo viejo
chatbot_whatsapp (agradecimientos a Felipe Martínez por esa lógica).
"""
import logging
import re
from datetime import datetime, timedelta
from odoo import models, api, fields

_logger = logging.getLogger(__name__)

HTML_TAGS = re.compile(r"<[^>]+>")


def _clean_html(text):
    """Limpia HTML del texto."""
    if not text:
        return ""
    return re.sub(HTML_TAGS, "", text).strip()


def _sanitize_phone(phone):
    """Normaliza un teléfono al formato +E164 (solo dígitos con + adelante)."""
    if not phone:
        return ''
    return '+' + re.sub(r'\D', '', phone)


def _get_local_number(phone):
    """Devuelve el número local sin código país ni '9' argentino."""
    sanitized = re.sub(r'\D', '', phone or '')
    if sanitized.startswith('549'):
        return sanitized[3:]
    if sanitized.startswith('54'):
        return sanitized[2:]
    return sanitized


class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override de create. Si es un mensaje entrante, dispara el agente
        DESPUÉS de que el registro fue creado normalmente.
        """
        records = super().create(vals_list)

        # Solo procesar entrantes
        for record in records:
            try:
                self._maybe_trigger_agent(record)
            except Exception as e:
                _logger.exception("Error disparando agente para wa.msg %s: %s", record.id, e)
                # NO propagamos la excepción para no romper la recepción del mensaje

        return records

    def _maybe_trigger_agent(self, wa_message):
        """Decide si dispara el agente para este mensaje y, si sí, lo dispara."""
        # 1) Solo entrantes
        if wa_message.state not in ('received', 'inbound'):
            return

        # 2) Tiene contenido?
        plain_body = _clean_html(wa_message.body or "")
        phone_raw = wa_message.mobile_number or getattr(wa_message, 'phone', '') or ""
        if not phone_raw:
            return

        # 3) Está habilitado el agente?
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config.enabled:
            _logger.info("⏸️  Agente deshabilitado (config). Ignorando mensaje %s.", wa_message.id)
            return

        # 3.1) v1.13/v1.14 — ¿Es una nota de voz? (sin texto pero con audio adjunto).
        # La API de Claude no entiende audio. ⚠️ NO transcribimos acá: la llamada
        # HTTP a OpenAI NUNCA debe correr dentro del webhook (bloquearía la
        # respuesta a Meta y puede tumbar la entrega de mensajes). Solo MARCAMOS el
        # audio; lo transcribe el cron, fuera del webhook (v1.14). Si la
        # transcripción está apagada o sin key, avisamos a Joaco y cortamos.
        audio_att = None
        if not plain_body:
            candidate = self._get_audio_attachment(wa_message)
            if candidate:
                ConfigModel = self.env['cristal.agent.config'].sudo()
                if config.enable_audio_transcription and ConfigModel.get_openai_key():
                    audio_att = candidate
                else:
                    self._notify_joaco_audio(
                        wa_message, "Transcripción de audio desactivada o sin API key")
                    return

        # 2.b) Sin texto ni audio → nada que procesar
        if not plain_body and not audio_att:
            return

        # 3.5) ¿Esta cuenta WA está en la lista de cuentas permitidas?
        # Si restricted_wa_account_ids tiene cuentas, solo procesamos esas.
        # Si está vacío, procesamos todas (compatibilidad hacia atrás).
        allowed_accounts = config.restricted_wa_account_ids if hasattr(config, 'restricted_wa_account_ids') else None
        if allowed_accounts and wa_message.wa_account_id:
            if wa_message.wa_account_id.id not in allowed_accounts.ids:
                _logger.info(
                    "⏭️  Mensaje %s ignorado: cuenta WA '%s' (id=%s) no está en cuentas permitidas %s",
                    wa_message.id, wa_message.wa_account_id.name,
                    wa_message.wa_account_id.id, allowed_accounts.ids
                )
                return

        # 4) Buscar / crear partner
        partner = self._find_or_create_partner(phone_raw)
        if not partner:
            _logger.warning("No se pudo identificar partner para mensaje %s", wa_message.id)
            return

        # 5) Obtener / crear memoria
        Memory = self.env['cristal.agent.memory'].sudo()
        memory = Memory.get_or_create(partner)
        memory.increment_received()

        # 6) Takeover humano activo? Bot pausado?
        if memory.is_takeover_active():
            _logger.info("🤫 Takeover activo para %s. Bot ignora el mensaje.", partner.name)
            return

        # 6.5) v1.9.0 — Detectar client_type y aplicar bypass institucional
        #
        # v1.9.10 FIX CRÍTICO: el wa_account_id del mensaje ENTRANTE manda
        # SIEMPRE. Antes la memoria histórica pisaba la detección, lo que
        # causaba el loop circular: cliente escribía primero a Crilimp →
        # memory.client_type='mayorista' → después escribía a Compras pero
        # el bot lo seguía tratando como mayorista → derivaba al canal donde
        # ya estaba.
        wa_account_id = wa_message.wa_account_id.id if wa_message.wa_account_id else None

        if wa_account_id:
            # Hay cuenta WA: la cuenta es autoridad sobre la memoria
            detected = config.detect_client_type(wa_account_id=wa_account_id, partner=partner)
            if detected != 'unknown':
                client_type = detected
                # Si la memoria histórica difiere, la actualizamos para reflejar
                # el canal actual del cliente (puede haber cambiado de canal).
                if memory.client_type != client_type:
                    old = memory.client_type
                    memory.sudo().write({'client_type': client_type})
                    _logger.info(
                        "🔄 client_type actualizado por wa_account: %s → %s "
                        "(partner=%s, wa_account=%s)",
                        old or '(none)', client_type, partner.name, wa_account_id
                    )
            else:
                # wa_account no resuelve (no está en la lista conocida) → fallback memoria
                client_type = memory.client_type or 'unknown'
        else:
            # Sin wa_account_id (cron, trigger manual): usar memoria como fallback
            client_type = memory.client_type or config.detect_client_type(partner=partner)

        _logger.info("🏷️  Client type para este mensaje: %s (wa_account=%s, partner=%s)",
                     client_type, wa_account_id, partner.name)

        # BYPASS: solo aplica a institucional. Para mayorista NUNCA hay bypass.
        should_bypass, bypass_reason = config.should_bypass_qualification(
            client_type=client_type,
            partner=partner,
            memory=memory,
        )
        if should_bypass:
            _logger.info(
                "🚦 Bypass institucional para %s — motivo: %s",
                partner.name, bypass_reason
            )
            # Activamos takeover indefinido y notificamos a Joaco
            memory.activate_takeover(reason=bypass_reason, duration_hours=0)
            self._notify_joaco_institutional_bypass(wa_message, partner, bypass_reason, plain_body)
            return

        # 7) Actualizar timestamp de último inbound
        partner.sudo().write({'agent_last_inbound_at': fields.Datetime.now()})

        # 8) Disparar el agente — con DEBOUNCE (v1.11.0).
        # Antes se disparaba un run completo por CADA mensaje entrante, de forma
        # sincrónica dentro del create(). Cuando el cliente mandaba una ráfaga
        # (típico: 5-9 mensajes en pocos minutos durante la calificación) eso
        # generaba 5-9 runs caros y 5-9 burbujas de respuesta. Ahora juntamos la
        # ráfaga: encolamos el texto y procesamos todo en UN run tras N segundos
        # de silencio. Resultado: menos costo + respuesta más completa y menos
        # "manda muchos mensajes".
        debounce = config.debounce_seconds or 0

        # v1.14 — Las notas de voz SIEMPRE van por la cola asíncrona, sin importar
        # el debounce: la transcripción (OpenAI) corre en el cron, jamás dentro del
        # webhook. Así el webhook responde al instante y no se puede volver a colgar.
        if audio_att:
            _logger.info("🎙️ Encolando nota de voz de %s para transcribir (async).",
                         partner.name)
            memory.enqueue_pending_audio(audio_att.id, wa_message=wa_message)
            self._schedule_debounce_cron(config)
            return

        if debounce <= 0:
            _logger.info("🚀 Disparando agente (sin debounce) para %s: %r",
                         partner.name, plain_body[:120])
            from ..services.claude_client import dispatch_agent_for_message
            dispatch_agent_for_message(self.env, wa_message, partner, memory, plain_body)
            return

        _logger.info("⏳ Encolando mensaje de %s (debounce %ss): %r",
                     partner.name, debounce, plain_body[:80])
        memory.enqueue_pending(plain_body, wa_message=wa_message)
        self._schedule_debounce_cron(config)

    def _schedule_debounce_cron(self, config):
        """Programa el cron one-shot del debounce apenas pase la ventana de
        silencio. (Hay además un cron de 1 min de fallback por si el trigger falla.)"""
        debounce = config.debounce_seconds or 0
        try:
            cron = self.env.ref('cristal_agent.cron_process_debounced', raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger(at=fields.Datetime.now() + timedelta(seconds=debounce + 1))
        except Exception as e:
            _logger.warning("No se pudo programar el trigger de debounce: %s", e)

    # ─────────── Notas de voz / transcripción (v1.13/v1.14) ───────────
    def _get_audio_attachment(self, wa_message):
        """Devuelve el primer ir.attachment de audio colgado del mensaje, o False.
        En Odoo, el media entrante de WhatsApp queda en mail_message_id.attachment_ids."""
        mm = wa_message.mail_message_id
        if not mm:
            return False
        for att in mm.attachment_ids:
            if (att.mimetype or '').lower().startswith('audio/'):
                return att
        return False

    def _notify_joaco_audio(self, wa_message, reason, partner=None):
        """Avisa a Joaco por canal interno cuando llega una nota de voz que el bot
        no procesó (transcripción apagada o fallida). Usable desde el webhook
        (wa_message) o desde el cron (partner como fallback)."""
        try:
            config = self.env['cristal.agent.config'].sudo().get_active()
            channel_id = config.internal_channel_id.id if config.internal_channel_id else 969
            channel = self.env['discuss.channel'].sudo().browse(channel_id)
            if not channel.exists():
                _logger.warning("Canal interno %s no existe — skip aviso de audio", channel_id)
                return
            phone = (wa_message.mobile_number if wa_message else None) \
                or ((partner.mobile or partner.phone) if partner else None) or '?'
            wa_account_name = wa_message.wa_account_id.name if (wa_message and wa_message.wa_account_id) else "?"
            msg = (
                f"🎙️ Nota de voz recibida (el bot no la procesó)\n"
                f"📞 WhatsApp: {phone}\n"
                f"🏷️ Cuenta WA: {wa_account_name}\n"
                f"⚠️ Motivo: {reason}\n"
                f"Escuchala y respondé vos."
            )
            channel.message_post(
                body=msg.replace('\n', '<br/>'),
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
            _logger.info("📣 Aviso de nota de voz enviado a canal %s", channel_id)
        except Exception as e:
            _logger.exception("Error notificando nota de voz a Joaco: %s", e)

    def _notify_joaco_institutional_bypass(self, wa_message, partner, reason, plain_body):
        """
        v1.9.0 — Notifica a Joaco vía canal interno cuando el bot se saltea
        la calificación institucional (cliente activo o ya calificado).
        """
        try:
            JOACO_INTERNAL_CHANNEL = 969  # Canal interno con Joaco

            channel = self.env['discuss.channel'].sudo().browse(JOACO_INTERNAL_CHANNEL)
            if not channel.exists():
                _logger.warning("Canal interno %s no existe — skip notificación", JOACO_INTERNAL_CHANNEL)
                return

            wa_account_name = wa_message.wa_account_id.name if wa_message.wa_account_id else "?"
            preview = plain_body[:120] if plain_body else ""

            msg = (
                f"🚦 Bypass institucional activado\n"
                f"👤 Cliente: {partner.name} (id={partner.id})\n"
                f"📞 WhatsApp: {wa_message.mobile_number}\n"
                f"🏷️ Cuenta WA: {wa_account_name}\n"
                f"💬 Motivo: {reason}\n"
                f"📨 Mensaje: \"{preview}\"\n\n"
                f"Atendelo manualmente."
            )
            channel.message_post(
                body=msg.replace('\n', '<br/>'),
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
            _logger.info("📣 Notificación de bypass enviada a canal %s", JOACO_INTERNAL_CHANNEL)
        except Exception as e:
            _logger.exception("Error notificando bypass institucional: %s", e)

    def _find_or_create_partner(self, phone_raw):
        """
        Lógica de búsqueda de partner por phone_sanitized.
        Reusa el approach del módulo viejo chatbot_whatsapp.
        """
        sanitized = _sanitize_phone(phone_raw)
        Partner = self.env['res.partner'].sudo()

        # Domain: phone_sanitized = sanitized
        domain = [('phone_sanitized', '=', sanitized)]

        # Caso especial Argentina: '+549...' también lo buscamos sin '9'
        if sanitized.startswith('+549'):
            without_9 = '+54' + sanitized[4:]
            domain = ['|', ('phone_sanitized', '=', sanitized), ('phone_sanitized', '=', without_9)]

        partner = Partner.search(domain, limit=1)

        if not partner:
            local = _get_local_number(phone_raw)
            partner = Partner.create({
                'name': f"WhatsApp: {local}",
                'phone': sanitized,
                'mobile': sanitized,
            })
            _logger.info("👤 Nuevo partner creado para %s (id=%s)", local, partner.id)
        else:
            _logger.info("✅ Partner identificado: %s (id=%s)", partner.name, partner.id)

        return partner
