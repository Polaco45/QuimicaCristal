{
    "name": "POS Fiscal Auto Journal",
    "version": "1.0",
    "depends": ["point_of_sale", "account"],
    "author": "Polaco & ChatGPT",
    "category": "Point of Sale",
    "description": "Aplica automáticamente el diario correspondiente a la posición fiscal del cliente en POS. Permite cambiarlo con un selector desplegable sin afectar la ficha del cliente.",
    "data": [],
    "assets": {
        "point_of_sale.assets": [
            "pos_fiscal_auto_journal/static/src/js/fiscal_journal_hook.js",
            "pos_fiscal_auto_journal/static/src/js/journal_selector_button.js",
            "pos_fiscal_auto_journal/static/src/xml/journal_selector_template.xml"
        ]
    },
    "installable": True,
    "application": False
}
