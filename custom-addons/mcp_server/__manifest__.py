{
    'name': 'MCP Server',
    'version': '18.0.1.1.0',
    'category': 'Technical',
    'summary': 'Model Context Protocol Server - Connect AI assistants to Odoo',
    'description': """
        Exposes Odoo data and operations via the Model Context Protocol (MCP).
        Allows AI assistants like Claude to securely interact with your Odoo instance
        through natural language, performing CRUD operations on configured models.

        v1.1 — Reportes en PDF (generate_report), cola de mensajes pendientes
        de WhatsApp (get_unanswered_messages), y modelos adicionales habilitados
        automáticamente vía upsert (no rompe configuración manual previa).
    """,
    'author': 'Química Cristal',
    'website': 'https://quimicacristal.odoo.com',
    'depends': [
        'base',
        'base_setup',
        'mail',
        'product',
        'sale',
        'crm',
        'account',
        'stock',
        'whatsapp',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/data.xml',
        'data/cron_data.xml',
        'views/mcp_api_key_views.xml',
        'views/mcp_model_access_views.xml',
        'views/mcp_report_access_views.xml',
        'views/mcp_pending_message_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
