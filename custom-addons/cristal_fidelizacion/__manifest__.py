# -*- coding: utf-8 -*-
{
    'name': 'Cristal — Fidelización automática',
    'version': '18.0.1.1.0',
    'summary': 'Flujos automáticos por WhatsApp para consumidor final: recordatorio de '
               'reposición, segunda compra, satisfacción y reseña, reactivación en '
               'escalera. Grupo de control, tope de frecuencia, registro de respuestas '
               'y conversiones. Arranca en modo prueba (no manda nada).',
    'author': 'Química Cristal',
    'category': 'Sales/Sales',
    'license': 'LGPL-3',
    'depends': ['cristal_minorista', 'whatsapp', 'loyalty', 'pos_loyalty'],
    'data': [
        'security/ir.model.access.csv',
        'data/flows.xml',
        'data/family_labels.xml',
        'data/cron.xml',
        'views/fidelizacion_views.xml',
    ],
    'application': False,
    'installable': True,
}
