# -*- coding: utf-8 -*-
"""
Hook en mail.message.

Maneja varios escenarios:

1. Mensaje humano en canal WhatsApp de un cliente:
   - Si es comando /off → activar takeover indefinido
   - Si es comando /on → desactivar takeover
   - Si es mensaje normal → takeover automático 1h (asume intervención manual)

2. Mensaje de Joaco en el canal interno Joaco↔Claudio (id 969 default):
   - Disparar el agente para que LEA el mensaje y actúe (aprender, ejecutar
     comando, responder pregunta, etc.)

3. Mensaje del bot mismo (con context from_cristal_agent=True):
   - Skip total, no hacer nada (evita loops)
"""
import logging
import re
from odoo import models, api, fields

_logger = logging.getLogger(__name__)

HTML_TAGS = re.compile(r"<[^>]+>")


def _clean_html(text):
    if not text:
        return ""
    return re.sub(HTML_TAGS, "", text).strip()


def _sanitize_phone(phone):
    if not phone:
        return ''
    return '+' + re.sub(r'\D', '', phone)


class MailMessage(models.Model):
    _inherit = 'mail.message'

    @api.model_create_multi
    def create(self, vals_list):
        # Si el contexto indica que viene del bot, no procesamos (evita loop)
        if self.env.context.get('from_cristal_agent'):
            return super().create(vals_list)

        note_subtype_id = self.env.ref('mail.mt_note').id
        processed = []

        # Para identificar canal interno y owner, leemos la config (con caché simple)
        config = self.env['cristal.agent.config'].sudo().get_active()
        internal_channel_id = config.internal_channel_id.id if config.internal_channel_id else 0
        owner_partner_id = config.owner_partner_id.id if config.owner_partner_id else 0
        bot_partner_id = config.bot_partner_id.id if config.bot_partner_id else 0

        # Mensajes que tras crearse deben disparar el agente para chat interno
        internal_messages_to_dispatch = []

        for vals in vals_list:
            author_id = vals.get('author_id')
            model = vals.get('model')
            res_id = vals.get('res_id')
            body = vals.get('body', '')

            # Solo procesamos mensajes en canales discuss con autor
            if not (model == 'discuss.channel' and author_id and res_id):
                processed.append(vals)
                continue

            author = self.env['res.partner'].sudo().browse(author_id)
            channel = self.env['discuss.channel'].sudo().browse(res_id)
            plain_body = _clean_html(body).strip().lower()

            # ───────────────────────────────────────────────────────────
            # CASO 2: Mensaje en el canal interno Joaco↔Claudio
            # ───────────────────────────────────────────────────────────
            if internal_channel_id and channel.id == internal_channel_id:
                # Solo disparar si es Joaco (owner). Si es el bot mismo, skip
                # (de todas formas el contexto from_cristal_agent ya filtra)
                if owner_partner_id and author.id == owner_partner_id:
                    # Chequear feature flag (con getattr por si el campo aún no existe
                    # durante la migración inicial del módulo)
                    if not getattr(config, 'enable_internal_channel_learning', True):
                        _logger.info(
                            "Hook canal interno: SKIP "
                            "(flag enable_internal_channel_learning=False)"
                        )
                        processed.append(vals)
                        continue
                    # Lo agregamos a la lista de mensajes a despachar DESPUÉS del create
                    internal_messages_to_dispatch.append({
                        'channel_id': channel.id,
                        'plain_text': _clean_html(body).strip(),
                        'vals_index': len(processed),
                    })
                processed.append(vals)
                continue

            # ───────────────────────────────────────────────────────────
            # CASO 1: Mensaje en canal WhatsApp de cliente — solo de humanos
            # ───────────────────────────────────────────────────────────

            # Solo si el autor es un usuario humano (tiene res.users) y NO es el bot
            if not author.user_ids:
                processed.append(vals)
                continue
            if bot_partner_id and author.id == bot_partner_id:
                processed.append(vals)
                continue

            # Solo procesamos en canales de WhatsApp
            try:
                channel_type = getattr(channel, 'channel_type', None)
                if channel_type != 'whatsapp':
                    processed.append(vals)
                    continue
            except Exception:
                processed.append(vals)
                continue

            # Identificar al cliente del canal (no al autor del mensaje)
            partner_to_manage = self._find_partner_in_channel(channel)
            if not partner_to_manage:
                processed.append(vals)
                continue

            Memory = self.env['cristal.agent.memory'].sudo()
            memory = Memory.get_or_create(partner_to_manage)

            # Comando /off — pausa indefinida
            if plain_body == '/off':
                memory.activate_takeover(
                    reason=f"Comando /off de {author.name}",
                    duration_hours=0,
                )
                vals['body'] = f"🤖 Bot DESACTIVADO indefinidamente para {partner_to_manage.name}."
                vals['subtype_id'] = note_subtype_id
                vals['message_type'] = 'comment'
                processed.append(vals)
                continue

            # Comando /on — reactivación
            if plain_body == '/on':
                memory.deactivate_takeover()
                vals['body'] = f"✅ Bot ACTIVADO para {partner_to_manage.name}."
                vals['subtype_id'] = note_subtype_id
                vals['message_type'] = 'comment'
                processed.append(vals)
                continue

            # Mensaje normal de un humano = takeover automático 1h
            if not memory.human_takeover:
                memory.activate_takeover(
                    reason=f"Intervención manual de {author.name}",
                    duration_hours=1,
                )

            processed.append(vals)

        # Crear los registros (esto invoca el create real)
        records = super().create(processed)

        # ───────────────────────────────────────────────────────────
        # Después del create: disparar el agente para mensajes internos de Joaco
        # ───────────────────────────────────────────────────────────
        if internal_messages_to_dispatch:
            from ..services.claude_client import dispatch_agent_for_internal_message
            for item in internal_messages_to_dispatch:
                idx = item['vals_index']
                try:
                    record = records[idx] if idx < len(records) else None
                    mail_msg_id = record.id if record else None
                    _logger.info(
                        "🧑‍💼 Joaco escribió en canal interno %s: %r — disparando agente",
                        item['channel_id'], item['plain_text'][:80]
                    )
                    # Disparamos el agente para que procese
                    channel = self.env['discuss.channel'].sudo().browse(item['channel_id'])
                    dispatch_agent_for_internal_message(
                        self.env, channel, item['plain_text'], mail_msg_id
                    )
                except Exception as e:
                    _logger.exception(
                        "Error despachando agente para mensaje interno: %s", e
                    )

        return records

    def _find_partner_in_channel(self, channel):
        """
        Identifica el partner cliente del canal WhatsApp.
        Estrategia:
          1. Si el canal tiene whatsapp_number, buscar partner por ese número
          2. Si no, buscar entre los partners del canal el que NO sea usuario interno
        """
        Partner = self.env['res.partner'].sudo()

        # Estrategia 1: por whatsapp_number
        if hasattr(channel, 'whatsapp_number') and channel.whatsapp_number:
            sanitized = _sanitize_phone(channel.whatsapp_number)
            domain = [('phone_sanitized', '=', sanitized)]
            if sanitized.startswith('+549'):
                without_9 = '+54' + sanitized[4:]
                domain = ['|', ('phone_sanitized', '=', sanitized), ('phone_sanitized', '=', without_9)]
            partner = Partner.search(domain, limit=1)
            if partner:
                return partner

        # Estrategia 2: partners del canal sin user
        try:
            root_partner_id = self.env.ref('base.partner_root').id
        except Exception:
            root_partner_id = False
        candidates = channel.channel_partner_ids.filtered(
            lambda p: not p.user_ids and (not root_partner_id or p.id != root_partner_id)
        )
        if len(candidates) == 1:
            return candidates

        return False
