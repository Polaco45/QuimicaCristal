{
    "name": "POS Fiscal Auto Journal",
    "version": "1.1",
    "depends": ["point_of_sale", "account"],
    "author": "Polaco & ChatGPT",
    "category": "Point of Sale",
    "description": "Aplica automáticamente el diario correspondiente a la posición fiscal del cliente en POS. Muestra botón de selección en pantalla de pago.",
    "data": [],
    "assets": {
        "point_of_sale.assets": [
            "pos_fiscal_auto_journal/static/src/js/fiscal_journal_hook.js",
            "pos_fiscal_auto_journal/static/src/js/payment_screen_extension.js",
            "pos_fiscal_auto_journal/static/src/xml/payment_screen_template.xml"
        ]
    },
    "installable": True,
    "application": False
}
