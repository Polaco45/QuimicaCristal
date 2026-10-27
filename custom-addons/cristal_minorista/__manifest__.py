# -*- coding: utf-8 -*-
{
    'name': 'Cristal — Minorista (datos base)',
    'version': '18.0.1.0.0',
    'summary': 'Cimientos del sistema minorista: cliente único por WhatsApp, tipo de cliente '
               '(consumidor final o negocio), origen de cada venta, consentimiento de '
               'marketing, ciclo de consumo por familia de producto y segmentos RFM, '
               'recalculados cada noche.',
    'author': 'Química Cristal',
    'category': 'Sales/Sales',
    'license': 'LGPL-3',
    'depends': ['sale', 'point_of_sale', 'l10n_ar', 'cristal_agent'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron.xml',
        'views/minorista_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'application': False,
    'installable': True,
}
