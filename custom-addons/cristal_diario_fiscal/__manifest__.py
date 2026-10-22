# -*- coding: utf-8 -*-
{
    'name': 'Cristal — Diario por posición fiscal',
    'version': '18.0.1.0.0',
    'summary': 'Cada factura sale por el diario que corresponde a la posición fiscal '
               'del cliente (POS, órdenes de venta y facturas a mano). Si el cliente '
               'no tiene posición fiscal se lo trata como Ventas X, y los clientes '
               'nuevos se crean sin posición fiscal.',
    'author': 'Química Cristal',
    'category': 'Accounting/Accounting',
    'license': 'LGPL-3',
    'depends': ['sale', 'point_of_sale', 'l10n_ar', 'pos_journal_multi_choice'],
    'data': [
        'views/account_fiscal_position_views.xml',
        'views/res_company_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'cristal_diario_fiscal/static/src/js/pos_order.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'application': False,
    'installable': True,
}
