{
    "name": "Cristal - Cotización con Ficha Técnica",
    "version": "18.0.1.0.0",
    "summary": "Reporte de cotización/pedido que adjunta las fichas técnicas "
    "de los productos SEIQ incluidos.",
    "description": """
Agrega un segundo reporte en las cotizaciones / pedidos de venta:
"Cotización + Ficha Técnica".

Genera exactamente el mismo PDF que el presupuesto estándar y, a continuación,
adjunta la ficha técnica (documento PDF cargado en el producto) de cada producto
que la tenga cargada. Las fichas se toman de los adjuntos del producto cuyo
nombre contiene "ficha" (p. ej. "Ficha tecnica SEIQ - STRONG"), soportando tanto
adjuntos binarios como enlaces URL (se descargan al vuelo).

El reporte estándar de presupuesto no se modifica: este es un reporte adicional
disponible en el menú Imprimir de la orden de venta.
""",
    "author": "Química Cristal",
    "website": "https://github.com/Polaco45/QuimicaCristal",
    "license": "LGPL-3",
    "category": "Sales",
    "depends": ["sale"],
    "data": [
        "report/sale_report_ficha.xml",
    ],
    "installable": True,
    "application": False,
    # Sus dependencias ('sale') ya están instaladas en el build de Odoo.sh,
    # por lo que se instala automáticamente sin pasar por Apps.
    "auto_install": True,
}
