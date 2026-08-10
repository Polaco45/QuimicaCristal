# -*- coding: utf-8 -*-
{
    'name': "Cristal Cobranza — Recordatorios de pago por WhatsApp",
    'version': '18.0.1.4.0',
    'summary': "Cadencia de cobranza (0/5/10/15/20 días) por WhatsApp con estado de cuenta + comprobantes",
    'description': """
Cristal Cobranza
================

Motor de cobranza proactiva para Química Cristal, montado sobre el agente
Claudio (cristal_agent). Recorre las facturas vencidas de cada cliente y ejecuta
una cadencia escalonada, anclada a la factura MÁS vencida (un solo hilo por
cliente, sin spam):

* Día 0  (vencimiento): recordatorio por WhatsApp con UN PDF "Estado de cuenta +
  comprobantes" (estado de cuenta segmentado + cada factura vencida embebida) y
  los datos de pago.
* Día +5: seguimiento por WhatsApp con el estado de cuenta (sin re-adjuntar las
  facturas) y un mensaje más directo.
* Día +10: ultimátum por WhatsApp advirtiendo que se aplicarán recargos.
* Día +15: actividad de LLAMADA al responsable.
* Día +20: actividad de VISITA presencial al responsable.

El estado de cuenta segmenta SIEMPRE "vencidas" vs "por vencer en los próximos N
días", con el total vencido a pagar y los datos de pago (CBU / alias).

Diseño:
* Reusa el envío de templates de WhatsApp (whatsapp.composer) y el logging del
  agente (cristal.agent.run), sin modificar cristal_agent.
* El cron nace DESACTIVADO. Activar sólo después de: (1) cargar datos de pago,
  (2) tener los 3 templates aprobados por Meta, (3) probar en staging.
""",
    'author': "Desarrollado para Joaquín Ramello / Química Cristal",
    'website': "https://www.quimicacristal.com.ar",
    'category': 'Accounting/Accounting',
    'license': 'LGPL-3',
    'depends': [
        'cristal_agent',
        'account',
        'whatsapp',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'report/estado_cuenta_templates.xml',
        'report/report_actions.xml',
        'data/cron.xml',
        'data/mail_templates.xml',
        'views/cobranza_action_views.xml',
        'views/cobranza_report_views.xml',
        'views/res_partner_views.xml',
        'views/agent_config_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': 'post_init_cobranza',
}
