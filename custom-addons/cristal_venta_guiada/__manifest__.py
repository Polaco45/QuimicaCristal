# -*- coding: utf-8 -*-
{
    'name': 'Cristal — Venta guiada POS',
    'version': '18.0.1.4.1',
    'summary': 'En el POS, cada producto que se carga muestra una sugerencia elegida por '
               'el sistema (combo, tamaño mayor o complemento según lo que compran los '
               'clientes) y al cobrar ofrece el producto de caja. Registra lo mostrado y '
               'aceptado y recalcula las sugerencias cada noche.',
    'author': 'Química Cristal',
    'category': 'Sales/Point of Sale',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron.xml',
        'views/venta_guiada_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'cristal_venta_guiada/static/src/js/venta_guiada.js',
            'cristal_venta_guiada/static/src/xml/venta_guiada.xml',
            'cristal_venta_guiada/static/src/scss/venta_guiada.scss',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'application': False,
    'installable': True,
}
