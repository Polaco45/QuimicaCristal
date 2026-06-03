# -*- coding: utf-8 -*-
{
    'name': 'Cristal — Relevamiento Plan Control',
    'version': '18.0.1.0.0',
    'summary': 'Relevamiento inicial presencial (Plan Control) colgado del cliente, '
               'visible desde el Lead. Captura infraestructura, insumos, proveedor, '
               'falencias y diagnóstico por sector para el reporte de mejora a 3 meses.',
    'author': 'Química Cristal',
    'category': 'Sales/CRM',
    'license': 'LGPL-3',
    'depends': ['crm', 'contacts', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'data/relevamiento_opcion_data.xml',
        'views/cristal_relevamiento_views.xml',
        'views/res_partner_views.xml',
        'views/crm_lead_views.xml',
        'views/menus.xml',
        'report/relevamiento_report.xml',
        'report/relevamiento_report_templates.xml',
    ],
    'application': False,
    'installable': True,
}
