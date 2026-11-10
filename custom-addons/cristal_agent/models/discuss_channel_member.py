# -*- coding: utf-8 -*-
"""Chats de WhatsApp silenciados para los usuarios que no los atienden.

Claudio contesta los WhatsApp; Joaco solo necesita ver lo importante (su canal interno con
Claudio, menciones y chats directos). Pero Odoo lo suma como miembro de cada chat nuevo de
WhatsApp (notify_user_ids de la cuenta), y cada chat sin leer infla el contador de Discuss
(llegó a 1.491 el 10/11/2026).

Solución: todo chat de WhatsApp en el que entre uno de los partners listados en el parámetro
``cristal_agent.whatsapp_silenciar_partner_ids`` (ids separados por coma; por defecto Joaco,
65374) nace **silenciado** (mute_until_dt lejano). Un chat silenciado no suma al contador ni
suena, pero sigue abierto y legible. ``_cristal_silenciar_whatsapp`` hace lo mismo con los
chats existentes y los marca como leídos (lo usa la migración 18.0.1.63.3).
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

PARAM_PARTNERS = "cristal_agent.whatsapp_silenciar_partner_ids"
DEFAULT_PARTNERS = "65374"  # Joaco
MUTE_FOREVER = "2099-12-31 00:00:00"


class DiscussChannelMember(models.Model):
    _inherit = "discuss.channel.member"

    @api.model
    def _cristal_partners_silenciados(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(PARAM_PARTNERS, DEFAULT_PARTNERS)
        ids = set()
        for chunk in (raw or "").split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                ids.add(int(chunk))
        return ids

    @api.model_create_multi
    def create(self, vals_list):
        members = super().create(vals_list)
        silenciados = self._cristal_partners_silenciados()
        if silenciados:
            a_silenciar = members.filtered(
                lambda m: m.partner_id.id in silenciados
                and m.channel_id.channel_type == "whatsapp"
                and not m.mute_until_dt
            )
            if a_silenciar:
                a_silenciar.sudo().write({"mute_until_dt": MUTE_FOREVER})
        return members

    @api.model
    def _cristal_silenciar_whatsapp(self, partner_ids=None, marcar_leidos=True):
        """Silencia (y opcionalmente marca como leídos) todos los chats de WhatsApp
        existentes de los partners dados. Idempotente."""
        partner_ids = list(partner_ids or self._cristal_partners_silenciados())
        if not partner_ids:
            return 0
        self.env["discuss.channel"].flush_model()
        self.flush_model()
        self.env["mail.message"].flush_model()
        if marcar_leidos:
            self.env.cr.execute(
                """
                UPDATE discuss_channel_member m
                   SET new_message_separator = GREATEST(
                           m.new_message_separator,
                           COALESCE((SELECT MAX(mm.id) + 1
                                       FROM mail_message mm
                                      WHERE mm.model = 'discuss.channel'
                                        AND mm.res_id = m.channel_id), 0))
                  FROM discuss_channel c
                 WHERE c.id = m.channel_id
                   AND c.channel_type = 'whatsapp'
                   AND m.partner_id IN %s
                """,
                (tuple(partner_ids),),
            )
            _logger.info("cristal_agent: %s chats de WhatsApp marcados como leídos", self.env.cr.rowcount)
        self.env.cr.execute(
            """
            UPDATE discuss_channel_member m
               SET mute_until_dt = %s
              FROM discuss_channel c
             WHERE c.id = m.channel_id
               AND c.channel_type = 'whatsapp'
               AND m.partner_id IN %s
               AND m.mute_until_dt IS NULL
            """,
            (MUTE_FOREVER, tuple(partner_ids)),
        )
        n = self.env.cr.rowcount
        _logger.info("cristal_agent: %s chats de WhatsApp silenciados", n)
        self.invalidate_model(["new_message_separator", "mute_until_dt", "message_unread_counter"])
        return n

    @api.model
    def _cristal_limpiar_bandeja(self, partner_ids=None):
        """Marca como leída toda la bandeja de entrada (mail.notification tipo inbox) de los
        partners dados. Limpieza puntual; idempotente."""
        partner_ids = list(partner_ids or self._cristal_partners_silenciados())
        if not partner_ids:
            return 0
        self.env["mail.notification"].flush_model()
        self.env.cr.execute(
            """
            UPDATE mail_notification
               SET is_read = TRUE, read_date = NOW() AT TIME ZONE 'UTC'
             WHERE res_partner_id IN %s
               AND notification_type = 'inbox'
               AND is_read IS NOT TRUE
            """,
            (tuple(partner_ids),),
        )
        n = self.env.cr.rowcount
        _logger.info("cristal_agent: %s avisos de la bandeja de entrada marcados como leídos", n)
        self.env["mail.notification"].invalidate_model(["is_read", "read_date"])
        self.env["mail.message"].invalidate_model()
        return n
