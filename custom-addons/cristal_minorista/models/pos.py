# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models

from .res_partner import wa_key

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # El ticket se factura igual a nombre de quien diga la caja (ej. Consumidor Final
    # Anónimo); esto sólo dice a qué cliente real corresponde la compra.
    cristal_customer_pid = fields.Integer(string='ID cliente identificado', copy=False)
    cristal_customer_id = fields.Many2one('res.partner', string='Cliente identificado', index=True, copy=False,
                                          help='Cliente que dejó su WhatsApp en la caja.')

    # La caja manda el ID como entero (el cliente puede no estar cargado en el POS) y
    # además manda cristal_customer_id vacío: el ID manda.
    def _cristal_customer_vals(self, vals):
        if vals.get('cristal_customer_pid'):
            partner = self.env['res.partner'].sudo().browse(vals['cristal_customer_pid']).exists()
            vals['cristal_customer_id'] = partner.id or False
        else:
            vals.pop('cristal_customer_id', None)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._cristal_customer_vals(dict(vals)) for vals in vals_list])

    def write(self, vals):
        return super().write(self._cristal_customer_vals(dict(vals)))


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _load_pos_data(self, data):
        res = super()._load_pos_data(data)
        try:
            anon = self.env['cristal.minorista.engine']._anonymous_partner_id()
            res['data'][0]['_cristal_min'] = {'anonymous_partner_id': anon or False}
        except Exception:
            _logger.exception("minorista: no pude armar los datos para la caja %s", self.config_id.name)
            res['data'][0]['_cristal_min'] = {}
        return res


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _load_pos_data_fields(self, config_id):
        return super()._load_pos_data_fields(config_id) + ['cristal_mkt_optin', 'cristal_mkt_optout']

    @api.model
    def cristal_pos_identify(self, phone, name=None, partner_id=None):
        """Alta desde la caja: el cliente deja su WhatsApp y acepta recibir avisos.

        Si el ticket ya tiene un cliente real, se le anota el celular (si no tenía) y el
        consentimiento. Si es anónimo, se busca por WhatsApp o se crea uno nuevo, sin
        responsabilidad AFIP (no cambia cómo se factura este ticket).
        Devuelve {'id', 'name'} o {'error'}."""
        key = wa_key(phone)
        if not key:
            return {'error': _("El número no parece un celular válido. Probá con característica, ej. 358 4123456.")}
        Partner = self.sudo().with_context(active_test=True)
        anon = self.env['cristal.minorista.engine']._anonymous_partner_id()
        partner = Partner.browse(partner_id).exists() if partner_id and partner_id != anon else Partner
        if not partner:
            partner = Partner.search([('cristal_wa_key', '=', key), ('parent_id', '=', False)],
                                     order='cristal_purchases_total desc, id', limit=1)
        if not partner:
            partner = Partner.create({
                'name': (name or '').strip() or _("Cliente WhatsApp %s", key),
                'mobile': '+54 9 %s' % key,
                'customer_rank': 1,
                'cristal_first_origin': 'local',
            })
        vals = {'cristal_mkt_optin': True, 'cristal_mkt_optin_source': 'local'}
        if not partner.cristal_wa_key:
            vals['mobile'] = '+54 9 %s' % key
        if name and name.strip() and partner.name.startswith(_("Cliente WhatsApp")):
            vals['name'] = name.strip()
        partner.write(vals)
        return {'id': partner.id, 'name': partner.name}
