
# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_affiliate_key = fields.Char(string='Affiliate Key', copy=False)

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            key = order.x_affiliate_key
            if not key:
                _logger.info('[affiliate_autopps] SO %s sin x_affiliate_key: no se crea PPS.', order.name or order.id)
                continue
            try:
                order._affiliate_create_pps(key)
            except Exception as e:
                _logger.exception('[affiliate_autopps] Error creando PPS para SO %s con key=%s: %s', order.name, key, e)
        return res

    def _affiliate_create_pps(self, key):
        """Crea un registro de PPS/visita en el primer modelo disponible.

        No rompe si no existen ciertos campos: arma vals dinámicamente.
        """
        self.ensure_one()
        env = self.env
        models_to_try = ['affiliate.visit', 'affiliate.order', 'affiliate.order_report', 'affiliate.pps']
        created = False
        for model_name in models_to_try:
            if model_name in env:
                Model = env[model_name].sudo()
                fields_map = Model._fields
                vals = {}
                if 'order_id' in fields_map:
                    vals['order_id'] = self.id
                if 'sale_order_id' in fields_map:
                    vals['sale_order_id'] = self.id
                if 'name' in fields_map:
                    vals['name'] = self.name
                if 'reference' in fields_map and 'reference' not in vals:
                    vals['reference'] = self.name
                if 'affiliate_key' in fields_map:
                    vals['affiliate_key'] = key
                if 'key' in fields_map:
                    vals['key'] = key
                if 'partner_id' in fields_map:
                    vals['partner_id'] = self.partner_id.id
                if 'amount_total' in fields_map:
                    vals['amount_total'] = self.amount_total
                if 'currency_id' in fields_map:
                    vals['currency_id'] = self.currency_id.id

                rec = Model.create(vals)
                created = True
                _logger.info('[affiliate_autopps] PPS creado en %s id=%s para SO %s con key=%s vals=%s', model_name, rec.id, self.name, key, vals)
                break

        if not created:
            _logger.warning('[affiliate_autopps] Ningún modelo destino disponible para PPS. Revisar app de afiliados instalada.')
