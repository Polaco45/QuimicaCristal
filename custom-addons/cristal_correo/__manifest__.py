{
    "name": "Cristal · Correo",
    "summary": "Todas las casillas de Ferozo dentro de Odoo: bandeja, respuestas y automatizaciones",
    "description": """
Química Cristal — panel de correo dentro de Odoo.

El correo de @quimicacristal.com.ar vive en Ferozo (DonWeb). Odoo solo recibía las
RESPUESTAS a mails enviados desde Odoo; un mail nuevo a admin@, info@, compras@... se
quedaba en Ferozo. Este módulo:

* Casillas: una ficha por cuenta de Ferozo. Odoo lee la casilla por IMAP (todos los
  mails, también copias ocultas) y los mails quedan igual en Ferozo.
* Bandeja: cada mail nuevo es una tarjeta en el proyecto de bandeja de la casilla
  (los que armó Sergio: Administración, Compras, General). Se responde desde la
  tarjeta y la respuesta sale DESDE la casilla (ej. admin@quimicacristal.com.ar).
* Respuesta automática opcional por casilla (nunca a remitentes automáticos).
""",
    "version": "18.0.1.1.0",
    "author": "Química Cristal",
    "license": "LGPL-3",
    "category": "Productivity/Discuss",
    "depends": ["mail", "project", "crm", "website_project"],
    "data": [
        "security/ir.model.access.csv",
        "views/mail_account_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
}
