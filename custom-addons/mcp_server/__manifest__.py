{
    'name': 'MCP Server',
    'version': '18.0.1.0.0',
    'category': 'Technical',
    'summary': 'Model Context Protocol Server - Connect AI assistants to Odoo',
    'description': """
        Exposes Odoo data and operations via the Model Context Protocol (MCP).
        Allows AI assistants like Claude to securely interact with your Odoo instance
        through natural language, performing CRUD operations on configured models.
    """,
    'author': 'Química Cristal',
    'website': 'https://quimicacristal.odoo.com',
    'depends': ['base', 'base_setup', 'product', 'sale', 'crm', 'account', 'stock'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/data.xml',
        'views/mcp_api_key_views.xml',
        'views/mcp_model_access_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
