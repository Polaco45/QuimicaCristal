# -*- coding: utf-8 -*-
from odoo import api, fields, models

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
            vals['cristal_origin'] = 'whatsapp_ia' if self.env.uid in bot_ids else 'manual'
        return super().create(vals_list)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    cristal_origin = fields.Selection(ORIGINS, string='Origen de la venta', index=True, copy=False,
                                      default='local')
    cristal_origin_ref = fields.Char(string='Referencia del origen', copy=False)
