from odoo import api, models


class AccountJournal(models.Model):
    _inherit = "account.journal"

    # Al conectar el Galicia (30/10/2026) la sincronización bancaria de Odoo le escribe
    # al diario la moneda de la cuenta del banco (ARS), y account_ux (check_currency) no
    # deja que un diario tenga la moneda de la compañía: "Solo puede utilizar una moneda
    # secundaria distinta a la moneda de la compañía (ARS)". En Odoo, la moneda de la
    # compañía en el diario es lo mismo que no tener moneda: se ignora ese valor.

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company = (
                self.env["res.company"].browse(vals["company_id"]) if vals.get("company_id") else self.env.company
            )
            if vals.get("currency_id") and vals["currency_id"] == company.currency_id.id:
                vals.pop("currency_id")
        return super().create(vals_list)

    def write(self, vals):
        currency_id = vals.get("currency_id")
        if not currency_id:
            return super().write(vals)
        same = self.filtered(lambda j: j.company_id.currency_id.id == currency_id)
        if not same:
            return super().write(vals)
        rest = {k: v for k, v in vals.items() if k != "currency_id"}
        res = super(AccountJournal, same).write(rest) if rest else True
        others = self - same
        if others:
            res = super(AccountJournal, others).write(vals) and res
        return res
