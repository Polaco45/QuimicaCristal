{
    'name': 'Cristal Institucional',
    'version': '18.0.1.0.0',
    'summary': 'Máquina de venta institucional: etapa de cada empresa calculada por hechos, '
               'próximo paso, ficha de cuenta e indicadores por cliente.',
    'author': 'Química Cristal',
    'category': 'Sales/Sales',
    'license': 'LGPL-3',
    'depends': ['sale_crm', 'sale_margin', 'stock', 'sales_team'],
    'data': [
        'data/cron.xml',
        'views/partner_views.xml',
        'views/menu.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'application': True,
    'installable': True,
}
