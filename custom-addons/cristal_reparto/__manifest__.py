# -*- coding: utf-8 -*-
{
    'name': 'Cristal — Reparto',
    'version': '18.0.1.0.1',
    'summary': 'Organiza la vuelta de reparto del día: al validar la PACK la entrega '
               'entra sola a la lista (ordenada por cercanía desde el local), el '
               'repartidor la reordena, y al entregar cada pedido se le avisa por '
               'WhatsApp al próximo cliente que es el que sigue.',
    'author': 'Química Cristal',
    'category': 'Inventory/Delivery',
    'license': 'LGPL-3',
    'depends': ['stock', 'whatsapp', 'cristal_ruteo'],
    'data': [
        'security/ir.model.access.csv',
        'views/cristal_reparto_views.xml',
        'views/stock_picking_views.xml',
    ],
    'application': False,
    'installable': True,
}
