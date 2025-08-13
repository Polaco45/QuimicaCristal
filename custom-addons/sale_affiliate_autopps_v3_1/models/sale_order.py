# -*- coding: utf-8 -*-
import logging
from odoo import models, fields
from odoo.http import request

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_affiliate_key = fields.Char(string="Affiliate Key", copy=False, index=True)

    def _find_affiliate_partner(self, key):
        Partner = self.env["res.partner"].sudo()
        partner_fields = ["res_affiliate_key", "affiliate_key", "wk_affiliate_key", "affkey"]
        for f in partner_fields:
            if f in Partner._fields:
                dom = [(f, "=", key)]
                if "is_affiliate" in Partner._fields:
                    dom.append(("is_affiliate", "=", True))
                partner = Partner.search(dom, limit=1)
                if partner:
                    return partner
        for model_name in ["affiliate.partner", "affiliate.affiliate", "wk.affiliate.partner"]:
            Model = self.env.get(model_name)
            if not Model:
                continue
            for f in ["key", "affiliate_key", "res_affiliate_key"]:
                if f in Model._fields:
                    rec = Model.sudo().search([(f, "=", key)], limit=1)
                    if rec and "partner_id" in Model._fields and rec.partner_id:
                        return rec.partner_id.sudo()
        return Partner.browse(False)

    def _log(self, msg):
        try:
            _logger.info("[sale_affiliate_autopps] %s", msg)
        except Exception:
            pass

    def _create_affiliate_visits_pps(self):
        Visit = self.env["affiliate.visit"].sudo()
        Website = self.env["website"].sudo()

        for so in self:
            if not so.x_affiliate_key:
                self._log(f"SO {so.name}: sin x_affiliate_key, no se crea PPS.")
                continue

            partner = self._find_affiliate_partner(so.x_affiliate_key)
            if not partner:
                self._log(f"SO {so.name}: no se encontró partner para key {so.x_affiliate_key}.")
                continue

            current_website = so.website_id or Website.get_current_website()
            aff_program = False
            if current_website:
                aff_program = self.env["affiliate.program"].sudo().search([
                    ("website_id", "=", current_website.id)
                ], limit=1)

            ip = ""
            try:
                ip = request.httprequest.environ.get("REMOTE_ADDR") if request else ""
            except Exception:
                ip = ""

            created = 0
            for line in so.order_line:
                if hasattr(line, "is_delivery") and line.is_delivery:
                    continue
                if Visit.search_count([("sales_order_line_id", "=", line.id)]):
                    continue
                vals = {
                    "affiliate_method": "pps",
                    "affiliate_key": so.x_affiliate_key,
                    "affiliate_partner_id": partner.id,
                    "url": "",
                    "ip_address": ip,
                    "type_id": line.product_id.product_tmpl_id.id,
                    "affiliate_type": "product",
                    "type_name": line.product_id.id,
                    "sales_order_line_id": line.id,
                    "convert_date": fields.Datetime.now(),
                    "affiliate_program_id": aff_program.id if aff_program else False,
                    "website_id": current_website.id if current_website else False,
                    "product_quantity": int(line.product_uom_qty or 0),
                    "is_converted": True,
                }
                Visit.create(vals)
                created += 1
            self._log(f"SO {so.name}: creados {created} affiliate.visit PPS.")

    def action_confirm(self):
        res = super().action_confirm()
        self._create_affiliate_visits_pps()
        return res
