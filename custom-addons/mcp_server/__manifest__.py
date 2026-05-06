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
        (ir.attachment, ir.model, mail.activity.type, discuss.channel.member,
        product.tag, etc).
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
        'data/report_access_data.xml',
        'data/cron_data.xml',
        'views/mcp_api_key_views.xml',
        'views/mcp_model_access_views.xml',
        'views/mcp_report_access_views.xml',
        'views/mcp_pending_message_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
