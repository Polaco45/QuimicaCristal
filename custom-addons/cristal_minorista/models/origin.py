# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models

AD_ATTRIBUTION_DAYS = 14

ORIGINS = [
    ('local', 'Local'),
    ('web', 'Web'),
    ('whatsapp_ia', 'WhatsApp (Claudio)'),
    ('manual', 'Carga manual'),
    ('anuncio', 'Anuncio'),
    ('referido', 'Referido'),
    ('alianza', 'Alianza'),
    ('recordatorio', 'Recordatorio de reposición'),
    ('reactivacion', 'Reactivación'),
    ('otro', 'Otro'),
]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    cristal_origin = fields.Selection(ORIGINS, string='Origen de la venta', index=True, copy=False,
                                      help='De dónde vino la venta. Se completa sola; un flujo o un '
                                           'anuncio la puede marcar con el contexto "cristal_origin".')
    cristal_origin_ref = fields.Char(string='Referencia del origen', copy=False,
                                     help='Identificador del anuncio, código de referido o de alianza.')

    @api.model
    def _cristal_bot_user_ids(self):
        """Usuarios con los que trabaja Claudio (sus pedidos son de WhatsApp)."""
        ids = set(self.env['cristal.agent.config'].sudo().search([]).bot_user_id.ids)
        return list(ids or {self.env.ref('base.user_root').id})

    @api.model_create_multi
    def create(self, vals_list):
        ctx_origin = self.env.context.get('cristal_origin')
        bot_ids = None
        for vals in vals_list:
            if vals.get('cristal_origin'):
                continue
            if ctx_origin:
                vals['cristal_origin'] = ctx_origin
                vals.setdefault('cristal_origin_ref', self.env.context.get('cristal_origin_ref'))
                continue
            if vals.get('website_id'):
                vals['cristal_origin'] = 'web'
                continue
            if bot_ids is None:
                bot_ids = self._cristal_bot_user_ids()
            if self.env.uid in bot_ids:
                ad = self._cristal_ad_reference(vals.get('partner_id'))
                vals['cristal_origin'] = 'anuncio' if ad else 'whatsapp_ia'
                if ad:
                    vals['cristal_origin_ref'] = ad
            else:
                vals['cristal_origin'] = 'manual'
        return super().create(vals_list)

    @api.model
    def _cristal_ad_reference(self, partner_id, days=AD_ATTRIBUTION_DAYS):
        """Mensaje precargado del anuncio con el que el cliente abrió el chat (últimos
        días), o False. Los mensajes van en el parámetro cristal_minorista.ad_messages,
        separados por |."""
        phrases = [p.strip() for p in (self.env['ir.config_parameter'].sudo().get_param(
            'cristal_minorista.ad_messages') or '').split('|') if p.strip()]
        partner = self.env['res.partner'].sudo().browse(partner_id).exists() if partner_id else False
        if not (phrases and partner):
            return False
        since = fields.Datetime.now() - timedelta(days=days)
        channels = self.env['discuss.channel'].sudo().search([
            ('channel_type', '=', 'whatsapp'),
            ('channel_partner_ids', 'in', partner.commercial_partner_id.child_ids.ids + [partner.id,
                                                                                          partner.commercial_partner_id.id])])
        if not channels:
            return False
        for phrase in phrases:
            if self.env['mail.message'].sudo().search_count([
                    ('model', '=', 'discuss.channel'), ('res_id', 'in', channels.ids),
                    ('date', '>=', since), ('body', 'ilike', phrase)]):
                return phrase[:120]
        return False


class PosOrder(models.Model):
    _inherit = 'pos.order'

    cristal_origin = fields.Selection(ORIGINS, string='Origen de la venta', index=True, copy=False,
                                      default='local')
    cristal_origin_ref = fields.Char(string='Referencia del origen', copy=False)
