{
    "name": "Cristal - Recibido por en remito de entrega",
    "version": "18.0.1.1.0",
    "summary": "Registra quién recibe la entrega y lo imprime en el remito, junto a la firma.",
    "description": """
Agrega un campo 'Recibido por' en las órdenes de entrega (stock.picking) para
asentar el nombre / aclaración de la persona que recibe el pedido al momento de
firmar, y lo muestra en el PDF del remito de entrega debajo de la firma.
""",
    "author": "Química Cristal",
    "website": "https://github.com/Polaco45/QuimicaCristal",
    "license": "LGPL-3",
    "category": "Inventory/Delivery",
    "depends": ["stock", "stock_barcode"],
    "data": [
        "views/stock_picking_views.xml",
        "report/report_deliveryslip.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cristal_delivery_receiver/static/src/barcode_signature_patch.js",
        ],
    },
    "installable": True,
    "application": False,
    # auto_install: se instala solo en el build de Odoo.sh (sus dependencias
    # 'stock' y 'stock_barcode' ya están instaladas), sin pasar por Apps.
    "auto_install": True,
}
