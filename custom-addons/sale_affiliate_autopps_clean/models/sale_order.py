# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.http import request

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Guardamos la key tal como la trajiste en los módulos anteriores
    x_affiliate_key = fields.Char(string='Affiliate Key', copy=False, index=True)

    # -------------------------
    # Helpers
    # -------------------------
    def _get_request(self):
        """Devuelve el request si estamos en contexto HTTP, si no None."""
        try:
            return request if request and hasattr(request, 'httprequest') else None
        except Exception:
            return None

    def _find_key_in_http(self):
        """Busca la clave en URL o cookies."""
        req = self._get_request()
        if not req:
            return None

        # 1) Querystring
        qs = req.httprequest.args if hasattr(req, 'httprequest') else {}
        for k in ['aff_key', 'affkey', 'affiliate_key', 'aff']:
            if k in qs and qs.get(k):
                return qs.get(k)

        # 2) Cookies
        cookies = req.httprequest.cookies or {}
        for k in ['aff_key', 'affiliate_key', 'aff']:
            if k in cookies and cookies.get(k):
                return cookies.get(k)

        return None

    def _persist_key_cookie(self, key):
        """Guarda cookie aff_key para que persista entre pasos."""
        req = self._get_request()
        if not req or not key:
            return
        try:
            # set cookie for 30 days
            max_age = 60 * 60 * 24 * 30
            req.set_cookie('aff_key', key, max_age=max_age)
        except Exception as e:
            _logger.debug('No se pudo setear cookie aff_key: %s', e)

    def _set_order_aff_key_from_anywhere(self):
        """Si el pedido no tiene key, intenta tomarla de URL/cookie y la persiste."""
        for order in self:
            if order.x_affiliate_key:
                continue
            key = order._find_key_in_http()
            if key:
                try:
                    order.with_context(skip_aff_capture=True).write({'x_affiliate_key': key})
                    _logger.info("[affiliate_autopps] SO %s: persistido x_affiliate_key=%s desde cookie/url.", order.name or order.id, key)
                    order._persist_key_cookie(key)
                except Exception as e:
                    _logger.warning("No se pudo persistir x_affiliate_key en SO %s: %s", order.id, e)

    # -------------------------
    # Hook: creación/escritura
    # -------------------------
    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        # Intentar capturar la clave en flujo web
        try:
            orders._set_order_aff_key_from_anywhere()
        except Exception as e:
            _logger.debug("create/_set_order_aff_key_from_anywhere falló: %s", e)
        return orders

    def write(self, vals):
        res = super().write(vals)
        # Sólo intentamos capturar si aún no existe
        if not self.env.context.get('skip_aff_capture'):
            try:
                self._set_order_aff_key_from_anywhere()
            except Exception as e:
                _logger.debug("write/_set_order_aff_key_from_anywhere falló: %s", e)
        return res

    # -------------------------
    # PPS / Comisión al confirmar
    # -------------------------
    def _affiliate_model_exists(self, model_name):
        try:
            self.env[model_name]
            return True
        except Exception:
            return False

    def _find_affiliate_by_key(self, key):
        """Intenta encontrar un afiliado a partir de la key en varios modelos posibles."""
        if not key:
            return None, None

        candidates = [
            ('affiliate.affiliate', 'key'),
            ('affiliate.request', 'key'),
            ('affiliate.request', 'affiliate_key'),
            ('affiliate.partner', 'key'),
            ('affiliate.referrer', 'key'),
        ]
        for model, field in candidates:
            if not self._affiliate_model_exists(model):
                continue
            try:
                model_env = self.env[model].sudo()
                if field in model_env._fields:
                    rec = model_env.search([(field, '=', key)], limit=1)
                    if rec:
                        # intentamos obtener partner/affiliate_id según cómo se llame el campo
                        partner = None
                        if 'partner_id' in rec._fields:
                            partner = rec.partner_id
                        return rec, partner
            except Exception as e:
                _logger.debug("Búsqueda de afiliado en %s falló: %s", model, e)
        return None, None

    def _prepare_affiliate_visit_vals(self, affiliate_rec, partner, key):
        """Devuelve vals robustos para crear un registro de visita/PPS en el modelo disponible."""
        order = self
        vals = {}

        # Campos comunes
        for fname, value in [
            ('name', f"PPS {order.name or order.id}"),
            ('sale_order_id', order.id),
            ('order_id', order.id),
            ('website_id', getattr(order, 'website_id', False) and order.website_id.id or False),
            ('company_id', order.company_id.id if order.company_id else False),
            ('partner_id', order.partner_id.id if order.partner_id else False),
            ('affiliate_id', affiliate_rec.id if affiliate_rec else False),
            ('key', key),
            ('affiliate_key', key),
            ('amount_total', order.amount_total),
            ('amount', order.amount_total),
            ('currency_id', order.currency_id.id if order.currency_id else False),
            ('state', 'done'),
            ('status', 'done'),
            ('is_converted', True),
            ('date', fields.Datetime.now()),
        ]:
            # sólo setear si el campo existe
            v = value
            if isinstance(v, bool) and not v:
                pass
            for model_name in ['affiliate.visit', 'affiliate.order', 'affiliate.order_report', 'affiliate.pps']:
                try:
                    model = self.env[model_name]
                    # usamos el primer modelo que exista
                    if fname in model._fields:
                        vals[fname] = value
                    # no rompemos nada si el modelo no existe
                except Exception:
                    continue
        return vals

    def _create_affiliate_pps_record(self):
        """Crea un registro de PPS/visita si hay key y módulo de afiliados instalado.
        No lanza errores si el modelo/campos no existen."""
        for order in self:
            key = order.x_affiliate_key
            if not key:
                _logger.info("[affiliate_autopps] SO %s sin x_affiliate_key: no se crea PPS.", order.name or order.id)
                continue

            affiliate_rec, partner = order._find_affiliate_by_key(key)
            target_model = None
            for m in ['affiliate.visit', 'affiliate.order', 'affiliate.order_report', 'affiliate.pps']:
                if order._affiliate_model_exists(m):
                    target_model = m
                    break

            if not target_model:
                _logger.info("[affiliate_autopps] No se encontró un modelo de destino para PPS (affiliate.*). Se omite.")
                continue

            try:
                vals = order._prepare_affiliate_visit_vals(affiliate_rec, partner, key)
                # filtramos vals a los campos del modelo que vamos a usar
                model_env = self.env[target_model].sudo()
                clean_vals = {k: v for k, v in vals.items() if k in model_env._fields}
                if 'sale_order_id' in model_env._fields and not clean_vals.get('sale_order_id'):
                    clean_vals['sale_order_id'] = order.id
                if 'name' in model_env._fields and not clean_vals.get('name'):
                    clean_vals['name'] = f"PPS {order.name or order.id}"

                rec = model_env.create(clean_vals)
                _logger.info("[affiliate_autopps] PPS creado en %s id=%s para SO %s con key=%s", target_model, rec.id, order.name or order.id, key)
            except Exception as e:
                _logger.warning("[affiliate_autopps] Error creando PPS para SO %s: %s", order.name or order.id, e)

    def action_confirm(self):
        res = super().action_confirm()
        try:
            self._create_affiliate_pps_record()
        except Exception as e:
            _logger.warning("No se pudo crear PPS al confirmar SO %s: %s", self.ids, e)
        return res
