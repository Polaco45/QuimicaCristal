{
    "name": "Sale: Payment methods by Delivery",
    "summary": "Restringe métodos de pago por método de entrega en eCommerce",
    "version": "18.0.1.1.0",
    "license": "LGPL-3",
    "author": "Tu Equipo",
    "depends": ["website_sale", "payment", "delivery"],
    "data": [
        "views/payment_provider_views.xml",
        "views/delivery_carrier_views.xml",
    ],
    "installable": True,
}
