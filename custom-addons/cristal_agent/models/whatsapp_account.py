# -*- coding: utf-8 -*-
"""v1.78 — Registra en Odoo lo que se manda desde el celular (convivencia)."""
import logging

from odoo import models
from odoo.tools import plaintext2html

_logger = logging.getLogger(__name__)

_MEDIA = {'image': 'foto', 'video': 'video', 'document': 'archivo', 'audio': 'audio',
          'sticker': 'sticker', 'location': 'ubicación', 'contacts': 'contacto'}


class WhatsAppAccount(models.Model):
    _inherit = 'whatsapp.account'

    def _cristal_process_echoes(self, value):
        """`value` de un webhook smb_message_echoes: mensajes que mandó el negocio desde
        la app del celular. Se guardan como salientes ya enviados (no se reenvían)."""
        self.ensure_one()
        for echo in value.get('message_echoes', []):
            try:
                uid, to, kind = echo.get('id'), echo.get('to'), echo.get('type')
                if not uid or not to or kind in ('revoke', 'edit'):
                    continue
                number = self._format_incoming_from_number(to)
                channel = self._find_active_channel(number, create_if_not_found=True)
                if not channel:
                    continue
                content = echo.get(kind) or {}
                if kind == 'text':
                    text = content.get('body') or ''
                else:
                    text = f"[{_MEDIA.get(kind, 'mensaje')} enviado desde el celular]"
                    if isinstance(content, dict) and content.get('caption'):
                        text += ' ' + content['caption']
                self._cristal_post_echo(channel, uid, text)
            except Exception:  # noqa: BLE001
                _logger.exception("Eco de WhatsApp sin registrar: %s", echo.get('id'))

    def _cristal_post_echo(self, channel, msg_uid, text):
        """Deja en el chat un mensaje que ya salió desde el celular. Devuelve el
        whatsapp.message (vacío si ya estaba registrado)."""
        self.ensure_one()
        WA = self.env['whatsapp.message'].sudo()
        if not text or WA.search_count([('msg_uid', '=', msg_uid)]):
            return WA
        config = self.env['cristal.agent.config'].sudo().get_active()
        is_purchase = bool(config.purchase_wa_account_id == self)
        # v1.83 — WhatsApp de empresas en modo borrador: mismo trato que Compras.
        is_client_draft = bool(getattr(config, 'client_draft_enabled', False)
                               and config.client_draft_wa_account_id == self)
        draft_owner = (config.client_draft_owner_user_id or config.owner_user_id) \
            if is_client_draft else False
        author = (config.purchase_owner_user_id.partner_id if is_purchase else False) \
            or (draft_owner.partner_id if draft_owner else False) \
            or self.notify_user_ids[:1].partner_id \
            or config.bot_partner_id or self.env.ref('base.partner_root')
        # En Compras no interviene el agente de ventas: se evita su takeover (que además
        # crearía una memoria de cliente para el proveedor). En las demás cuentas, que una
        # persona escriba desde el celular SÍ pausa a Claudio, como cuando escribe en Odoo.
        MM = self.env['mail.message'].sudo()
        if is_purchase or is_client_draft:
            MM = MM.with_context(from_cristal_agent=True)
        mail_msg = MM.create({
            'author_id': author.id, 'body': plaintext2html(text),
            'message_type': 'whatsapp_message', 'model': 'discuss.channel',
            'res_id': channel.id, 'subtype_id': self.env.ref('mail.mt_comment').id,
        })
        wa_msg = WA.with_context(from_cristal_agent=True).create({
            'mail_message_id': mail_msg.id, 'wa_account_id': self.id,
            'mobile_number': '+' + (channel.whatsapp_number or '').lstrip('+'),
            'message_type': 'outbound', 'state': 'sent', 'msg_uid': msg_uid,
        })
        if is_purchase:
            self.env['cristal.agent.supplier.draft'].sudo().mark_handled_by_phone(channel)
        if is_client_draft:
            self.env['cristal.agent.client.draft'].sudo().mark_handled_by_phone(channel)
        return wa_msg
