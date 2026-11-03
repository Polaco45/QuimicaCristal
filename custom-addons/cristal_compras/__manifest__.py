{
    "name": "Cristal · Compras (agente)",
    "summary": "Órdenes y pedidos de precio al proveedor por WhatsApp o mail, listas mensuales y respuestas en la orden",
    "description": """
Química Cristal — agente de Compras (pedido de Sergio, 03/11/2026).

* Orden aprobada: cuando Sergio confirma la orden, sale el PDF de la orden al proveedor
  por el canal de su ficha («Hola [nombre], te paso un pedido. Muchas gracias.»).
* Pedido de precio: botón en la solicitud de presupuesto; pide precio y fecha de despacho.
* Listas: el primer lunes de cada mes arma los pedidos de lista de los proveedores que no
  la mandaron en el mes (salvo los exceptuados) y quedan para que Sergio los apruebe. A los
  que cotizan materias primas (Química Olivos) les pasa el listado de lo que trabajamos.
* Listas que llegan por WhatsApp o mail: se guardan solas en «Listas de precios recibidas».
* Respuestas de proveedores: quedan en la orden; si hablan de precio, fecha o condiciones,
  le queda una actividad a Compras.
* Ningún mensaje sale sin un OK de un responsable de Compras; no confirma compras ni paga.
""",
    "version": "18.0.1.0.2",
    "author": "Química Cristal",
    "license": "LGPL-3",
    "category": "Inventory/Purchase",
    "depends": ["purchase", "whatsapp", "mail", "project"],
    "data": [
        "security/ir.model.access.csv",
        "report/raw_materials_report.xml",
        "data/cron.xml",
        "views/res_partner_views.xml",
        "views/purchase_order_views.xml",
        "views/price_list_views.xml",
        "views/list_request_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
}
