{
    'name': "Chatbot WhatsApp",
    'version': '1.0',
    'summary': "Integración de un chatbot (OpenAI) con el WhatsApp integrado en Odoo.",
    'description': """
        Este módulo extiende el modelo whatsapp.message para enviar respuestas automáticas
        mediante OpenAI al recibir mensajes entrantes.
    """,
    'author': "Tu Nombre",
    'website': "https://tusitio.com",
    'category': 'Tools',
    'license': 'LGPL-3',
    'depends': ['whatsapp_connector'],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
