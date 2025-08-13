# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from odoo.http import request

_logger = logging.getLogger(__name__)

def _safe_request_session_get(name):
    try:
        return request.session.get(name)
    except Exception:
        return None

def _safe_cookie_get(name):
    try:
        return request.httprequest.cookies.get(name)
    except Exception:
        return None

class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Key que llega desde la URL/cookie. Sólo lectura para backend por seguridad.
    x_affiliate_key = fields.Char(string="Affiliate Key", copy=False, index=True, readonly=False)

    # -------------------------------
    # Helpers: obtención del aff_key
    # -------------------------------
    def _get_aff_key_from_anywhere(self):
        """Busca un aff_key válido en el siguiente orden:
        1) La propia orden (si ya lo tiene)
        2) request.session['x_affiliate_key']
        3) cookie 'aff_key' (por compatibilidad de temas)
        """
        self.ensure_one()
        if self.x_affiliate_key:
            return self.x_affiliate_key
        key = _safe_request_session_get("x_affiliate_key")
        if key:
            return key
        return _safe_cookie_get("aff_key")

    # -------------------------------------------
    # Propagar el aff_key al crear / escribir SO
    # -------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        # En entorno website, si hay key en sesión/cookie y la orden no lo tiene -> lo seteamos
        for so in orders:
            try:
                key = so._get_aff_key_from_anywhere()
                if key and not so.x_affiliate_key:
                    so.sudo().write({"x_affiliate_key": key})
                    _logger.info("[affiliate_autopps] SO %s: set x_affiliate_key=%s en create().", so.name, key)
            except Exception as e:
                _logger.debug("No se pudo propagar aff_key en create(): %s", e)
        return orders

    def write(self, vals):
        res = super().write(vals)
        # Si estamos en website y aún no hay key, intentamos completar
        for so in self:
            if not so.x_affiliate_key:
                try:
                    key = so._get_aff_key_from_anywhere()
                    if key:
                        so.sudo().write({"x_affiliate_key": key})
                        _logger.info("[affiliate_autopps] SO %s: set x_affiliate_key=%s en write().", so.name, key)
                except Exception as e:
                    _logger.debug("No se pudo propagar aff_key en write(): %s", e)
        return res

    # --------------------------------------------------------
    # PPS: crear visitas/conversión al confirmar la venta
    # --------------------------------------------------------
    def _find_affiliate_partner(self, key):
        """Intenta encontrar el partner del afiliado por varias columnas conocidas."""
        Partner = self.env["res.partner"].sudo()
        for col in ["res_affiliate_key", "affiliate_key", "wk_affiliate_key", "affkey", "x_affiliate_key"]:
            if col in Partner._fields:
                partner = Partner.search([(col, "=", key)], limit=1)
                if partner:
                    return partner
        # fallback: partners con campo 'is_affiliate' y llave en nota
        if "is_affiliate" in Partner._fields:
            partner = Partner.search([("is_affiliate", "=", True), ("name", "ilike", key)], limit=1)
            if partner:
                return partner
        return self.env["res.partner"]

    def _get_current_website(self):
        try:
            return request.website
        except Exception:
            return self.env["website"].sudo().search([], limit=1)

    def _get_affiliate_program_for_website(self, website):
        Program = self.env["affiliate.program"].sudo() if "affiliate.program" in self.env else None
        if not Program:
            return None
        domain = []
        # Intentar varios nombres de campos comunes
        if website:
            if "website_id" in Program._fields:
                domain = [("website_id", "=", website.id)]
            elif "website_ids" in Program._fields:
                domain = [("website_ids", "in", website.id)]
        rec = Program.search(domain or [], limit=1)
        return rec or None

    def _create_pps_visits(self):
        """Crea registros en affiliate.visit marcados como conversión.
        Seguro: usa sólo campos que existen en el modelo, nunca rompe checkout.
        """
        VisitModel = self.env.get("affiliate.visit")
        if not VisitModel:
            _logger.info("[affiliate_autopps] affiliate.visit no existe. Me detengo.")
            return

        for so in self:
            key = so.x_affiliate_key
            if not key:
                _logger.info("[affiliate_autopps] SO %s sin x_affiliate_key: no se crea PPS.", so.name)
                continue

            website = self._get_current_website()
            partner = so._find_affiliate_partner(key) if hasattr(so, "_find_affiliate_partner") else self._find_affiliate_partner(key)
            program = self._get_affiliate_program_for_website(website)

            # Campos disponibles en affiliate.visit
            avail = VisitModel._fields

            base_vals = {}
            # Partner (varios posibles nombres)
            for fname in ["partner_id", "affiliate_partner_id", "affiliate_id", "referrer_id"]:
                if fname in avail and partner:
                    base_vals[fname] = partner.id
                    break
            if "website_id" in avail and website:
                base_vals["website_id"] = website.id
            if "affiliate_key" in avail:
                base_vals["affiliate_key"] = key
            if "convert_date" in avail:
                base_vals["convert_date"] = fields.Datetime.now()
            if "affiliate_program_id" in avail and program:
                base_vals["affiliate_program_id"] = program.id
            if "order_id" in avail:
                base_vals["order_id"] = so.id
            if "sale_order_id" in avail:
                base_vals["sale_order_id"] = so.id
            if "amount_total" in avail:
                base_vals["amount_total"] = so.amount_total
            if "currency_id" in avail:
                base_vals["currency_id"] = so.currency_id.id
            if "is_converted" in avail:
                base_vals["is_converted"] = True

            created = 0
            for line in so.order_line:
                vals = dict(base_vals)  # copia
                if "product_id" in avail:
                    vals["product_id"] = line.product_id.id
                if "product_qty" in avail:
                    vals["product_qty"] = line.product_uom_qty
                if "product_quantity" in avail:
                    vals["product_quantity"] = int(line.product_uom_qty or 0)
                # Crear sin fallar por campos desconocidos
                VisitModel.sudo().create(vals)
                created += 1

            _logger.info("[affiliate_autopps] SO %s: creadas %s visitas convertidas (PPS).", so.name, created)

    def action_confirm(self):
        res = super().action_confirm()
        try:
            self._create_pps_visits()
        except Exception as e:
            # Nunca romper la confirmación. Logueamos y seguimos.
            _logger.warning("Fallo al crear PPS (silenciado para no romper checkout): %s", e)
        return res
