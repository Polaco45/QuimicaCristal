
# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from odoo.http import request

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_affiliate_key = fields.Char(string="Affiliate Key", copy=False, index=True)

    # -------- helpers --------
    def _get_aff_key_from_request(self):
        """Intento seguro: leer aff_key desde querystring o cookies si hay request.
        Nunca rompe si no hay entorno HTTP (backend, cron, etc.).
        """
        try:
            if not request:
                return False
            # querystring primero
            key = None
            if request.httprequest:
                key = request.httprequest.args.get("aff_key")
                if not key:
                    # comunes alternativos
                    for cname in ("aff_key", "affiliate_key", "affiliate"):
                        key = request.httprequest.cookies.get(cname)
                        if key:
                            break
            if key:
                key = (key or "").strip()
                if len(key) > 64:
                    key = key[:64]
                return key
            return False
        except Exception:
            return False

    @api.model_create_multi
    def create(self, vals_list):
        # intenta persistir el affiliate key en la creación del carrito si viene por request/cookie
        new_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            if not vals.get("x_affiliate_key"):
                aff = self._get_aff_key_from_request()
                if aff:
                    vals["x_affiliate_key"] = aff
                    _logger.info("[affiliate_autopps] create(): persistido x_affiliate_key=%s en SO.", aff)
            new_vals_list.append(vals)
        return super().create(new_vals_list)

    def write(self, vals):
        # si aún no tiene clave, intenta tomarla de la request/cookie (no rompe si no hay request)
        records_without_key = self.filtered(lambda so: not so.x_affiliate_key)
        if records_without_key and "x_affiliate_key" not in vals:
            aff = self._get_aff_key_from_request()
            if aff:
                vals = dict(vals, x_affiliate_key=aff)
                _logger.info("[affiliate_autopps] write(): persistido x_affiliate_key=%s en SO %s.", aff, ",".join(records_without_key.mapped("name")))
        return super().write(vals)

    def action_confirm(self):
        res = super().action_confirm()
        try:
            self._create_pps_records()
        except Exception as e:
            _logger.exception("[affiliate_autopps] error creando PPS: %s", e)
        return res

    # -------- PPS creation --------
    def _create_pps_records(self):
        """Crea/convierte registros en affiliate.visit (cuando exista) al confirmar.
        No falla si el modelo no está disponible. Usa sólo campos existentes en el modelo.
        """
        try:
            Visit = self.env["affiliate.visit"]
        except Exception:
            Visit = None

        for order in self:
            key = (order.x_affiliate_key or "").strip()
            if not key:
                _logger.info("[affiliate_autopps] SO %s sin x_affiliate_key: no se crea PPS.", order.name)
                continue

            if not Visit:
                _logger.warning("[affiliate_autopps] affiliate.visit no está disponible en el registro: no se crea PPS para %s.", order.name)
                continue

            # Verificación de campos disponibles
            visit_fields = Visit._fields
            have = lambda f: f in visit_fields

            vals_common = {}
            if have("affiliate_key"):
                vals_common["affiliate_key"] = key
            if have("partner_id") and order.partner_id:
                vals_common["partner_id"] = order.partner_id.id
            if have("website_id") and order.website_id:
                vals_common["website_id"] = order.website_id.id
            if have("currency_id") and order.currency_id:
                vals_common["currency_id"] = order.currency_id.id
            if have("amount_total"):
                vals_common["amount_total"] = order.amount_total
            if have("convert_date"):
                vals_common["convert_date"] = fields.Datetime.now()
            if have("is_converted"):
                vals_common["is_converted"] = True
            # enlace con SO
            if have("order_id"):
                vals_common["order_id"] = order.id
            elif have("sale_order_id"):
                vals_common["sale_order_id"] = order.id

            # Si ya existe una visita con esa clave y sin convertir, la convertimos
            visit = None
            try:
                domain = []
                if have("affiliate_key"):
                    domain.append(("affiliate_key", "=", key))
                if have("is_converted"):
                    domain.append(("is_converted", "=", False))
                if domain:
                    visit = Visit.sudo().search(domain, order="id desc", limit=1)
            except Exception:
                visit = None

            if visit:
                try:
                    visit.sudo().write(vals_common)
                    _logger.info("[affiliate_autopps] SO %s: PPS convertida sobre visita #%s con key=%s.", order.name, visit.id, key)
                except Exception as ee:
                    _logger.exception("[affiliate_autopps] SO %s: no pude escribir visita existente: %s. Intento crear nueva.", order.name, ee)
                    Visit.sudo().create(vals_common)
                    _logger.info("[affiliate_autopps] SO %s: PPS creada (nueva visita) con key=%s.", order.name, key)
            else:
                Visit.sudo().create(vals_common)
                _logger.info("[affiliate_autopps] SO %s: PPS creada (nueva visita) con key=%s.", order.name, key)
