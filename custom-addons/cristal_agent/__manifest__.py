# -*- coding: utf-8 -*-
{
    'name': "Cristal Agent — Claudio (Mayorista)",
    'version': '18.0.1.11.3',
    'summary': "Agente comercial autónomo (Claude AI) para Cristal Mayorista",
    'description': """
Cristal Agent — Claudio
========================

Agente comercial autónomo basado en Claude (Anthropic) para Química Cristal.

Atiende clientes Mayoristas vía WhatsApp Business, ejecuta el ciclo comercial
completo (calificación, conversión, onboarding, sistema de niveles, fidelización),
mantiene una base de conocimiento dinámica y se comporta como un empleado real
del equipo: aprende, escala, hace seguimientos, asienta en CRM.

Scope inicial: clientes con etiqueta Mayorista. Otros segmentos (Consumidor Final,
Empresa) se incorporan en versiones posteriores.

Características principales
---------------------------

* Recepción de mensajes WhatsApp con respuesta inmediata (sin cron)
* Calificación automática de mayoristas (5 preguntas conversacionales)
* Cadencias de seguimiento programadas (Fase 2, 3, 4, 5 de la estrategia)
* Sistema de niveles BRONCE / PLATA / ORO con recálculo mensual automático
* Detección de churn y workflow de recuperación a 45 días
* Base de conocimiento editable (precios, ofertas, políticas, observaciones)
* Aprendizaje continuo: el agente guarda enseñanzas dadas por Joaco en chat
* Escalación automática a Joaco con contexto cuando lo amerita
* Análisis de imágenes (visión multimodal) y manejo de attachments
* Auditoría completa de cada ejecución (log persistente)
* Dashboard de KPIs en tiempo real
""",
    'author': "Anthropic Claude (desarrollado para Joaquín Ramello / Química Cristal)",
    'website': "https://www.quimicacristal.com.ar",
    'category': 'Sales/CRM',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'sale',
        'sale_management',
        'account',
        'crm',
        'stock',
        'whatsapp',
        'product',
        'contacts',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        # security primero
        'security/ir.model.access.csv',
        'security/ir_rule.xml',

        # data (config y cron antes que views — usan menos refs cruzadas)
        'data/ir_config_data.xml',
        'data/cron_jobs.xml',
        'data/default_knowledge.xml',
        'data/default_cadences.xml',
        'data/campaign_broadcast.xml',

        # views (los que definen acciones primero, menu al final)
        'views/agent_config_views.xml',
        'views/agent_run_views.xml',
        'views/agent_knowledge_views.xml',
        'views/agent_offer_views.xml',
        'views/agent_memory_views.xml',
        'views/agent_cadence_views.xml',
        'views/agent_dashboard.xml',
        'views/res_partner_views.xml',
        'views/product_mayorista_catalog_views.xml',
        'views/actions_by_client_type.xml',
        'views/menu.xml',  # ← AL FINAL: el menú referencia las acciones de los archivos anteriores
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_load_prompt',
}
