# -*- coding: utf-8 -*-
{
    'name': 'Cristal — Plan de Visitas',
    'version': '18.0.3.2.0',
    'summary': 'Plan de visitas manual en la ficha del cliente: regla (frecuencia + día), '
               'el calendario se arma solo, y el vendedor organiza "Mi día", pospone y '
               'registra en las notas al cerrar. El plan sigue al cliente toda la vida '
               '(prospecto → ganado → reposición). Rústico, sin geolocalización.',
    'description': """
Cristal — Plan de Visitas (manual)
==================================
La regla vive en la oportunidad (crm.lead): frecuencia (semanal/quincenal/mensual)
+ día de la semana. Desde la "próxima visita" se arma el Calendario y "Mi día".

  · El vendedor organiza a la mañana (Mi día): reordena, pospone, agrega.
  · Al cerrar: "Visité hoy" registra en las notas internas con fecha, marca la
    actividad de visita como hecha y agenda la próxima; "Posponer" mueve la fecha.
  · Todo pegado al CRM (contacto, notas, cotizaciones, actividades, etapa).

Rústico a propósito: sin geolocalización automática, sin zonas por cercanía, sin
ruteo por mapa ni crons. El vendedor manda; el sistema ordena y recuerda.

(Los modelos de geo/zonas quedan disponibles pero sin interfaz; el módulo de
reparto reusa el geocodificador cuando hace falta.)
""",
    'author': 'Química Cristal',
    'category': 'Sales/CRM',
    'license': 'LGPL-3',
    'depends': ['base_geolocalize', 'contacts', 'crm', 'mail', 'cristal_agent'],
    'data': [
        'security/visitas_security.xml',
        'security/ir.model.access.csv',
        'data/cron_jobs.xml',
        'wizards/visita_wizard_views.xml',
        'views/res_partner_visitas_views.xml',
        'views/cristal_visita_log_views.xml',
    ],
    'application': False,
    'installable': True,
}
