
# -*- coding: utf-8 -*-
{
    'name': 'Affiliate PPS on Confirm (Clean)',
    'summary': 'Persist affiliate key on sale orders from URL/cookie without overriding checkout routes.',
    'version': '18.0.1.0.0',
    'category': 'Website/Website',
    'license': 'LGPL-3',
    'author': 'ChatGPT',
    'website': 'https://example.com',
    'depends': ['website_sale', 'sale'],
    'data': [],
    'assets': {
        'web.assets_frontend': [
            'sale_affiliate_autopps_clean/static/src/js/aff_capture.js',
        ],
    },
    'installable': True,
    'application': False,
}
