from odoo import SUPERUSER_ID, api

# ADHOC dejó estos dos términos sin traducir en el es.po de l10n_ar_payment_bundle
# (la vista heredada pisa los <span> del reporte de l10n_ar_tax, que sí los traduce).
RECEIPT_TRANSLATIONS = {
    "Total Paid": "Total Pagado",
    "Total Imputed": "Total Imputado",
}


def translate_receipt_report(env):
    view = env.ref("l10n_ar_payment_bundle.report_payment_receipt_document", raise_if_not_found=False)
    if not view:
        return
    langs = env["res.lang"].search([("code", "like", "es%")]).mapped("code")
    if langs:
        view.update_field_translations("arch_db", {lang: dict(RECEIPT_TRANSLATIONS) for lang in langs})


def post_init_hook(env):
    translate_receipt_report(env)
