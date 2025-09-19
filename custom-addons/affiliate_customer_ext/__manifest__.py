# __manifest__.py (v18)
{
    "name": "Affiliate Customer Extension",
    "version": "18.0.1.0.0",
    "summary": "Muestra el cliente en visitas de afiliado (backend y portal)",
    'depends': ['affiliate_management', 'website', 'portal', 'website_sale'],
    'data': [
    'views/affiliate_visit_views.xml',   # backend
    'views/portal_templates.xml',        # QWeb portal/website
    ],
    "assets": {
        "web.assets_frontend": [
            "affiliate_customer_ext/views/portal_templates.xml",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
}
