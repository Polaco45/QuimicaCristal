# -*- coding: utf-8 -*-

from odoo import models


GROUP_VIEW_SALE_MARGIN = "qc_hide_sale_margin.group_view_sale_margin"


class QCHideSaleMarginHook(models.AbstractModel):
    _name = "qc.hide.sale.margin.hook"
    _description = "QC Hide Sale Margin Hook"

    def _register_hook(self):
        """Restrict margin/cost fields to the View Sale Margin group.

        This avoids redefining field types, so it is safer across Odoo versions
        where sale_margin fields can be Float, Monetary, or computed fields.
        """
        result = super()._register_hook()

        targets = {
            # Sale order header margins
            "sale.order": [
                "margin",
                "margin_percent",
            ],

            # Sale order line cost/margins
            "sale.order.line": [
                "purchase_price",
                "margin",
                "margin_percent",
            ],

            # Sales analysis/report fields, if present
            "sale.report": [
                "margin",
                "margin_percent",
                "purchase_price",
            ],
        }

        for model_name, field_names in targets.items():
            try:
                model = self.env[model_name]
            except KeyError:
                continue

            for field_name in field_names:
                field = model._fields.get(field_name)
                if field:
                    field.groups = GROUP_VIEW_SALE_MARGIN

        return result
