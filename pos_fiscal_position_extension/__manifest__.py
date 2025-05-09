{
    "name": "POS Fiscal Position Extension",
    "version": "1.0",
    "depends": ["point_of_sale", "account"],
    "author": "Polaquito & ChatGPT",
    "category": "Point of Sale",
    "description": "Aplica automáticamente la posición fiscal del cliente en el POS y prepara la base para selector de diario.",
    "data": [],
    "assets": {
        "point_of_sale.assets": [
            "pos_fiscal_position_extension/static/src/js/fiscal_position_hook.js",
        ]
    },
    "installable": True,
    "application": False,
}
