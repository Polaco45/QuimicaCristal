# -*- coding: utf-8 -*-
{
    'name': 'Quimica Cristal · Reporte Mensual Plan Control',
    'version': '18.0.1.2.1',
    'category': 'Sales/CRM',
    'summary': 'Reporte mensual de consumo para clientes del Plan Control',
    'description': """
Reporte Mensual Plan Control · Quimica Cristal
==============================================

Genera automáticamente el día 1 de cada mes un PDF de reporte de consumo
para cada cliente con la etiqueta 'Plan Control', y lo envía por email.

Características principales:
* Cálculo sobre TOTAL con IVA (no subtotal)
* Notas de crédito RESTAN del total
* Detección automática multi-sucursal por partner_shipping_id
* Categorización por product.template.categ_id (5 macro categorías)
* Wizard de descarga manual con selector de cliente y período
* Cron mensual automático
* Solo datos duros, sin interpretaciones

Autor: Joaquin Ramello - Quimica Cristal (Crilim S.A.S.)
""",
    'author': 'Quimica Cristal',
    'website': 'https://quimicacristal.com.ar',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'account',
        'product',
        'contacts',
    ],
    'data': [
        # Security
        'security/reporte_groups.xml',
        'security/ir.model.access.csv',

        # Data
        'data/res_partner_category_data.xml',
        'data/paperformat_data.xml',
        'data/mail_template_data.xml',
        'data/cron_data.xml',

        # Reports
        'report/reporte_report.xml',
        'report/reporte_template.xml',

        # Views
        'views/reporte_mensual_views.xml',
        'wizards/wizard_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
