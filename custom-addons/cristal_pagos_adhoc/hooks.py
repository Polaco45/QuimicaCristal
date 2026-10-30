# ADHOC dejó estos dos términos sin traducir en el es.po de l10n_ar_payment_bundle
# (la vista heredada pisa los <span> del reporte de l10n_ar_tax, que sí los traduce).
# Las claves son los términos tal como los extrae xml_translate (con las etiquetas).
RECEIPT_TRANSLATIONS = {
    "<strong><span>Total Paid</span></strong>": "<strong><span>Total Pagado</span></strong>",
    "<strong><span>Total Imputed</span></strong>": "<strong><span>Total Imputado</span></strong>",
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
