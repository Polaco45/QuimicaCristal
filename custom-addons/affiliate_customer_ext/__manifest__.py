# __manifest__.py
{
    "name": "Affiliate Customer Extension",
    "version": "18.0.1.0.0",
    "summary": "Muestra el cliente en visitas de afiliado (backend y portal)",
    "depends": ["affiliate_management", "website", "portal", "website_sale"],
    "data": [
        "views/affiliate_visit_views.xml",   # backend
        "views/portal_templates.xml",        # QWeb portal/website
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
