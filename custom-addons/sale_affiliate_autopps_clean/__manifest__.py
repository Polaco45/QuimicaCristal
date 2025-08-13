
# -*- coding: utf-8 -*-
{
    'name': 'Affiliate PPS on Confirm (Auto) – Clean',
    'version': '18.0.1.0.1',
    'summary': 'Guarda aff_key y crea PPS al confirmar venta (Odoo 18) sin tocar el checkout',
    'category': 'Sales/Website',
    'author': 'ChatGPT',
    'license': 'LGPL-3',
    'depends': ['web', 'sale', 'website_sale'],
    'data': [],
    'assets': {
        'web.assets_frontend': [
            'sale_affiliate_autopps_clean/static/src/js/aff_capture.js',
        ],
    },
    'installable': True,
    'application': False,
}
