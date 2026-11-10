# -*- coding: utf-8 -*-
"""Actividades automáticas sin aviso en la bandeja de entrada.

Cada actividad que un cron / automatización (OdooBot, uid 1) le asigna a Joaco ("Generar
Reporte", "Promo x producto", "Ruta ...", NBA, etc.) le dejaba un "Te asignaron ..." en la
bandeja de entrada de Discuss: 1.165 sin leer el 10/11/2026. Las actividades siguen
creándose igual (se ven en el CRM y en el reloj de actividades), pero si las crea OdooBot
para un partner silenciado (parámetro ``cristal_agent.whatsapp_silenciar_partner_ids``) no
se manda el aviso. Las que asigna una persona sí avisan.
"""
from odoo import api, models, SUPERUSER_ID


class MailActivity(models.Model):
    _inherit = "mail.activity"

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.uid != SUPERUSER_ID or self.env.context.get("mail_activity_quick_update"):
            return super().create(vals_list)
        partners = self.env["discuss.channel.member"]._cristal_partners_silenciados()
        if not partners:
            return super().create(vals_list)
        user_ids = set(self.env["res.users"].sudo().search([("partner_id", "in", list(partners))]).ids)
        silenciosas = [v for v in vals_list if v.get("user_id") in user_ids]
        if not silenciosas:
            return super().create(vals_list)
        normales = [v for v in vals_list if v.get("user_id") not in user_ids]
        res = super(MailActivity, self.with_context(mail_activity_quick_update=True)).create(silenciosas)
        if normales:
            res |= super().create(normales)
        return res
