{
    'name': 'Affiliate PPS on Confirm (Auto) - Clean',
    'summary': 'Captura aff_key en pedidos web y crea PPS/visita al confirmar el pedido sin romper el checkout.',
    'version': '18.0.1.0.0',
    'category': 'Website/Website',
    'author': 'ChatGPT Fix',
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'depends': ['sale', 'website_sale'],
    # affiliate_management es opcional; si existe, usamos sus modelos.
    'external_dependencies': {},
    'data': [],
}
