{
    "name": "MRP Vendor BoM Cost",
    "version": "18.0.1.0.0",
    "summary": "Calcula el costo del producto desde la LdM usando el precio del proveedor",
    "license": "LGPL-3",
    "depends": ["mrp_account", "purchase"],
    "data": [
        "views/product_views.xml",
        "data/server_actions.xml",
    ],
    "installable": True,
    "application": False,
}
