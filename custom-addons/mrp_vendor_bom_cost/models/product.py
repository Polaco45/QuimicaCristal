from odoo import _, fields, models
from odoo.exceptions import UserError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def button_vendor_bom_cost(self):
        self.ensure_one()

        if self.product_variant_count != 1:
            raise UserError(
                _("El producto debe tener una única variante para actualizar el costo desde el proveedor.")
            )

        return self.product_variant_id.button_vendor_bom_cost()

    def action_vendor_bom_cost(self):
        templates = self.filtered(lambda t: t.product_variant_count == 1)
        skipped = len(self - templates)

        if not templates:
            raise UserError(_("No hay productos válidos para recalcular."))

        return templates.mapped("product_variant_id").action_vendor_bom_cost(skipped=skipped)


class ProductProduct(models.Model):
    _inherit = "product.product"

    def button_vendor_bom_cost(self):
        self.ensure_one()
        updated = 1 if self._set_price_from_first_vendor() else 0
        return self._vendor_supplier_cost_notification(updated=updated, skipped=0)

    def action_vendor_bom_cost(self, skipped=0):
        updated = 0
        for product in self:
            if product._set_price_from_first_vendor():
                updated += 1

        return self._vendor_supplier_cost_notification(updated=updated, skipped=skipped)

    def _vendor_supplier_cost_notification(self, updated=0, skipped=0):
        message = _("%s producto(s) actualizado(s).") % updated
        if skipped:
            message += " " + _("%s producto(s) omitido(s).") % skipped

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Costo desde proveedor"),
                "message": message,
                "type": "success" if updated else "warning",
                "sticky": False,
            },
        }

    def _set_price_from_first_vendor(self):
        self.ensure_one()

        supplierinfo = self._get_first_valid_supplierinfo_for_cost()
        if not supplierinfo:
            raise UserError(
                _("El producto '%s' no tiene un proveedor válido cargado en la pestaña Compra.")
                % self.display_name
            )

        discounted_price = supplierinfo.price * (1 - (supplierinfo.discount or 0.0) / 100.0)

        company = self.env.company
        discounted_price_company_currency = supplierinfo.currency_id._convert(
            discounted_price,
            company.currency_id,
            company,
            fields.Date.context_today(self),
        )

        vendor_uom = supplierinfo.product_uom or self.product_tmpl_id.uom_po_id or self.uom_id
        cost_in_product_uom = vendor_uom._compute_price(
            discounted_price_company_currency,
            self.uom_id,
        )

        self.standard_price = cost_in_product_uom
        return True

    def _get_first_valid_supplierinfo_for_cost(self):
        self.ensure_one()
        today = fields.Date.context_today(self)

        sellers = self.product_tmpl_id.seller_ids.filtered(
            lambda s: (
                (not s.company_id or s.company_id == self.env.company)
                and s.partner_id.active
                and (not s.product_id or s.product_id == self)
                and (not s.date_start or s.date_start <= today)
                and (not s.date_end or s.date_end >= today)
            )
        )

        return sellers[:1]