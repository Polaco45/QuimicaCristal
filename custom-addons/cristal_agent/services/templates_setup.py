# -*- coding: utf-8 -*-
"""
Helper para crear templates WhatsApp default del bot Claudio.

Los crea en estado 'draft' (Joaco después manda a aprobar a Meta desde la UI).
Si ya existen por nombre, NO los duplica.
Asigna wa_account_id automáticamente buscando la cuenta Crilimp.

Llamado desde migrations/18.0.1.8.0/post-migration.py.
"""
import logging
_logger = logging.getLogger(__name__)


# Definición declarativa de templates default
DEFAULT_TEMPLATES = [
    {
        'name': 'chequeo_post_muestra',
        'body': 'Hola {{1}}, ¿pudiste probar la muestra que te llegó? ¿Qué te pareció?',
        'variables': [
            {'name': '{{1}}', 'demo_value': 'Cliente', 'line_type': 'body'},
        ],
        'cadence_name_prefix': 'Chequeo post-muestra',
    },
    {
        'name': 'recordatorio_pre_compra',
        'body': 'Hola {{1}}, se acerca la fecha de reposición. Te paso esta opción: {{2}}',
        'variables': [
            {'name': '{{1}}', 'demo_value': 'Cliente', 'line_type': 'body'},
            {'name': '{{2}}', 'demo_value': 'lleva 200L de Jabón Extra al precio de 170L', 'line_type': 'body', 'field_type': 'free_text'},
        ],
        'cadence_name_prefix': 'Recordatorio pre-compra',
    },
    {
        'name': 'manejo_objeciones',
        'body': 'Hola {{1}}, te quería pasar esto: {{2}}',
        'variables': [
            {'name': '{{1}}', 'demo_value': 'Cliente', 'line_type': 'body'},
            {'name': '{{2}}', 'demo_value': 'tenemos envío bonificado esta semana', 'line_type': 'body', 'field_type': 'free_text'},
        ],
        'cadence_name_prefix': 'Manejo de objeciones',
    },
    {
        'name': 'ultima_oferta',
        'body': 'Hola {{1}}, última oportunidad para aprovechar: {{2}}',
        'variables': [
            {'name': '{{1}}', 'demo_value': 'Cliente', 'line_type': 'body'},
            {'name': '{{2}}', 'demo_value': 'envío bonificado + 5% extra si pasás 200L granel', 'line_type': 'body', 'field_type': 'free_text'},
        ],
        'cadence_name_prefix': 'Última oferta',
    },
    {
        'name': 'chequeo_post_compra',
        'body': 'Hola {{1}}, ¿qué tal te están resultando los productos? ¿Cómo viene la venta?',
        'variables': [
            {'name': '{{1}}', 'demo_value': 'Cliente', 'line_type': 'body'},
        ],
        'cadence_name_prefix': 'Chequeo post-compra',
    },
    {
        'name': 'producto_top',
        'body': 'Hola {{1}}, contame, de los productos que llevaste, ¿cuál te está rotando mejor?',
        'variables': [
            {'name': '{{1}}', 'demo_value': 'Cliente', 'line_type': 'body'},
        ],
        'cadence_name_prefix': 'Detectar producto top',
    },
    {
        'name': 'chequeo_14d',
        'body': 'Hola {{1}}. ¿Cómo viene la venta? ¿Necesitás algo?',
        'variables': [
            {'name': '{{1}}', 'demo_value': 'Cliente', 'line_type': 'body'},
        ],
        'cadence_name_prefix': 'Chequeo a 14 días',
    },
    {
        'name': 'chequeo_30d',
        'body': 'Hola {{1}}, hace un mes que no nos vemos por acá. Te traigo esto: {{2}}. ¿Le damos?',
        'variables': [
            {'name': '{{1}}', 'demo_value': 'Cliente', 'line_type': 'body'},
            {'name': '{{2}}', 'demo_value': '30L de regalo en cualquier producto a granel', 'line_type': 'body', 'field_type': 'free_text'},
        ],
        'cadence_name_prefix': 'Recordatorio 30 días',
    },
    {
        'name': 'recuperacion_45d',
        'body': 'Hola {{1}}, queremos volver a tenerte como cliente. Esta semana tenemos: {{2}}',
        'variables': [
            {'name': '{{1}}', 'demo_value': 'Cliente', 'line_type': 'body'},
            {'name': '{{2}}', 'demo_value': 'cualquier producto a precio Plata como bienvenida', 'line_type': 'body', 'field_type': 'free_text'},
        ],
        'cadence_name_prefix': 'Recuperación 45 días',
    },
    {
        'name': 'oferta_semanal_general',
        'body': 'Hola {{1}}! Oferta de la semana: {{2}}. Cualquier consulta estoy por acá.',
        'variables': [
            {'name': '{{1}}', 'demo_value': 'Cliente', 'line_type': 'body'},
            {'name': '{{2}}', 'demo_value': '120lts de Lavandina al precio de 100lts', 'line_type': 'body', 'field_type': 'free_text'},
        ],
        'cadence_name_prefix': 'Oferta semanal en producto top',
        'used_for_broadcast': True,
    },
]


def ensure_default_templates(env):
    """
    Crea los templates default si no existen. Asigna wa_account_id a la cuenta Crilimp.
    Asigna los templates a sus respectivas cadencias.
    Devuelve dict con resultados.
    """
    Template = env['whatsapp.template'].sudo()
    Account = env['whatsapp.account'].sudo()
    Cadence = env['cristal.agent.cadence'].sudo()
    config = env['cristal.agent.config'].sudo().search([('active', '=', True)], limit=1)

    # 1. Buscar cuenta Crilimp
    crilimp_account = Account.search([('name', 'ilike', 'Crilimp')], limit=1)
    if not crilimp_account:
        _logger.warning(
            "ensure_default_templates: NO se encontró cuenta WA Crilimp. "
            "Los templates se crearán SIN cuenta asignada. Asignala manualmente."
        )

    # 2. Determinar el model (necesario para crear templates en Odoo)
    crm_lead_model = env['ir.model'].sudo().search([('model', '=', 'crm.lead')], limit=1)

    created = 0
    skipped = 0
    assigned_to_cadence = 0

    for tpl_def in DEFAULT_TEMPLATES:
        existing = Template.search([('name', '=', tpl_def['name'])], limit=1)
        if existing:
            _logger.info("Template '%s' ya existe (id=%s) — skip creación", tpl_def['name'], existing.id)
            skipped += 1
            template = existing
        else:
            # Crear template en estado draft
            vals = {
                'name': tpl_def['name'],
                'body': tpl_def['body'],
                'lang_code': 'es_AR',
                'template_type': 'marketing',
                'model_id': crm_lead_model.id if crm_lead_model else False,
                'phone_field': 'mobile',
            }
            if crilimp_account:
                vals['wa_account_id'] = crilimp_account.id

            try:
                template = Template.create(vals)
                _logger.info("✅ Template '%s' creado (id=%s, estado=draft)", template.name, template.id)
                created += 1

                # Crear variables
                for var_def in tpl_def.get('variables', []):
                    try:
                        var_vals = {
                            'wa_template_id': template.id,
                            'name': var_def['name'],
                            'line_type': var_def.get('line_type', 'body'),
                            'demo_value': var_def.get('demo_value', ''),
                            'field_type': var_def.get('field_type', 'free_text'),
                        }
                        env['whatsapp.template.variable'].sudo().create(var_vals)
                    except Exception as ve:
                        _logger.warning("No se pudo crear variable %s en %s: %s",
                                        var_def['name'], template.name, ve)
            except Exception as e:
                _logger.exception("Error creando template '%s': %s", tpl_def['name'], e)
                continue

        # 3. Asignar a cadencia si existe
        cadence_prefix = tpl_def.get('cadence_name_prefix')
        if cadence_prefix:
            cad = Cadence.search([
                ('name', 'ilike', cadence_prefix),
                ('active', '=', True),
            ], limit=1)
            if cad and not cad.whatsapp_template_id:
                cad.whatsapp_template_id = template.id
                _logger.info("✅ Cadencia '%s' → template '%s'", cad.name, template.name)
                assigned_to_cadence += 1

        # 4. Si es el template del broadcast, asignarlo en config
        if tpl_def.get('used_for_broadcast') and config and not config.weekly_offer_template_id:
            config.weekly_offer_template_id = template.id
            _logger.info("✅ Broadcast semanal → template '%s'", template.name)

    # 5. Asegurar que restricted_wa_account_ids tenga Crilimp por default
    if crilimp_account and config and hasattr(config, 'restricted_wa_account_ids'):
        if not config.restricted_wa_account_ids:
            config.restricted_wa_account_ids = [(6, 0, [crilimp_account.id])]
            _logger.info("✅ Cuenta restringida default → Crilimp")

    return {
        'created': created,
        'skipped': skipped,
        'assigned_to_cadence': assigned_to_cadence,
        'crilimp_account_id': crilimp_account.id if crilimp_account else None,
    }
