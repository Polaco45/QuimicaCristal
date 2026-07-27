# -*- coding: utf-8 -*-
{
    'name': 'Cristal — Ruteo de Visitas',
    'version': '18.0.2.1.0',
    'summary': 'Planificador de rutas de visita para la fuerza de venta de calle: '
               'geolocalización automática, micro-zonas por día, priorización por '
               'etapa del CRM, ruta diaria en Kanban y control de visitas.',
    'description': """
Cristal — Ruteo de Visitas
==========================
Capa fina sobre cristal_agent + CRM que arma el recorrido diario de la
vendedora al estilo PJP (Plan de Jornada Permanente) de distribuidora:

  1. Geolocalización automática (Pieza 1 — este release):
     La vendedora carga la dirección de calle del cliente y el sistema lo
     ubica solo en el mapa (proveedor OpenStreetMap, sin costo). Un cron de
     respaldo procesa los pendientes cada pocos minutos y hay un botón para
     ubicar al instante.

  Próximas piezas: micro-zonas por día, frecuencia por valor, score de
  prioridad y generador de ruta diaria como actividades "Visitar Institución".
""",
    'author': 'Química Cristal',
    'category': 'Sales/CRM',
    'license': 'LGPL-3',
    'depends': ['base_geolocalize', 'contacts', 'crm', 'mail', 'cristal_agent'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron_jobs.xml',
        'data/server_actions.xml',
        'wizards/ruta_zona_autoassign_views.xml',
        'wizards/ruta_visita_postpone_views.xml',
        'views/cristal_ruta_zona_views.xml',
        'views/cristal_ruta_visita_views.xml',
        'views/res_partner_views.xml',
    ],
    'application': False,
    'installable': True,
}
