"""Helpers de setup para el módulo MCP Server.

Define listas de modelos y reportes que el módulo intenta habilitar por defecto,
con lógica de UPSERT que respeta lo que ya está configurado por el usuario.
Esto evita errores de duplicate key cuando se actualiza el módulo y ya había
configuración manual previa.
"""

import logging

_logger = logging.getLogger(__name__)


# Modelos que el patch v1.1 habilita por defecto en el MCP.
# Estructura: lista de tuplas (model_name, dict_de_valores)
# Si el modelo no existe (porque el módulo no está instalado en la base),
# simplemente se omite sin error.
DEFAULT_MODELS_TO_ENABLE = [
    # Modelos técnicos (resolución de IDs)
    ('ir.model', {
        'perm_read': True, 'perm_create': False, 'perm_write': False,
        'perm_unlink': False, 'max_records': 200,
    }),
    ('ir.actions.report', {
        'perm_read': True, 'perm_create': False, 'perm_write': False,
        'perm_unlink': False, 'max_records': 100,
    }),
    ('ir.attachment', {
        'perm_read': True, 'perm_create': True, 'perm_write': True,
        'perm_unlink': False, 'max_records': 50,
        'field_whitelist': 'name,mimetype,datas,res_model,res_id,description,type,url',
    }),

    # Mensajería interna
    ('mail.message', {
        'perm_read': True, 'perm_create': True, 'perm_write': False,
        'perm_unlink': False, 'max_records': 100,
    }),
    ('mail.activity', {
        'perm_read': True, 'perm_create': True, 'perm_write': True,
        'perm_unlink': False, 'max_records': 100,
    }),
    ('mail.activity.type', {
        'perm_read': True, 'perm_create': False, 'perm_write': False,
        'perm_unlink': False, 'max_records': 50,
    }),
    ('discuss.channel', {
        'perm_read': True, 'perm_create': True, 'perm_write': True,
        'perm_unlink': False, 'max_records': 50,
    }),
    ('discuss.channel.member', {
        'perm_read': True, 'perm_create': True, 'perm_write': True,
        'perm_unlink': True, 'max_records': 100,
    }),

    # WhatsApp
    ('whatsapp.message', {
        'perm_read': True, 'perm_create': True, 'perm_write': True,
        'perm_unlink': False, 'max_records': 100,
    }),
    ('whatsapp.template', {
        'perm_read': True, 'perm_create': True, 'perm_write': True,
        'perm_unlink': False, 'max_records': 100,
    }),
    ('whatsapp.account', {
        'perm_read': True, 'perm_create': False, 'perm_write': False,
        'perm_unlink': False, 'max_records': 10,
    }),

    # Productos auxiliares
    ('product.tag', {
        'perm_read': True, 'perm_create': False, 'perm_write': False,
        'perm_unlink': False, 'max_records': 100,
    }),

    # CRM auxiliares
    ('crm.team', {
        'perm_read': True, 'perm_create': False, 'perm_write': False,
        'perm_unlink': False, 'max_records': 20,
    }),
    ('crm.stage', {
        'perm_read': True, 'perm_create': False, 'perm_write': False,
        'perm_unlink': False, 'max_records': 30,
    }),
    ('crm.tag', {
        'perm_read': True, 'perm_create': False, 'perm_write': True,
        'perm_unlink': False, 'max_records': 100,
    }),
    ('res.partner.category', {
        'perm_read': True, 'perm_create': False, 'perm_write': True,
        'perm_unlink': False, 'max_records': 100,
    }),

    # Cola de mensajes pendientes (modelo del propio MCP)
    ('mcp.pending.message', {
        'perm_read': True, 'perm_create': False, 'perm_write': True,
        'perm_unlink': False, 'max_records': 100,
    }),
]


# Reportes pre-aprobados para ejecutar via generate_report.
# Estructura: (xml_id, name, description)
DEFAULT_REPORTS_TO_ENABLE = [
    (
        'product.action_report_pricelist',
        'Lista de precios',
        'Genera el PDF de lista de precios para los productos seleccionados, '
        'usando una pricelist específica. Parámetros típicos en data: '
        '{"pricelist_id": <id>, "quantities": [1]}',
    ),
    (
        'sale.action_report_saleorder',
        'Presupuesto de venta',
        'Genera el PDF de presupuesto/pedido de venta. '
        'Útil para enviar cotizaciones a clientes.',
    ),
    (
        'account.account_invoices',
        'Factura',
        'Genera el PDF de factura. Para enviar comprobantes a clientes.',
    ),
]


def setup_default_models(env):
    """Habilita modelos por defecto en mcp.model.access usando upsert.

    Si ya existe un registro para el modelo (sin importar su xml_id), se respeta
    la configuración existente y NO se sobreescribe. Solo crea entradas faltantes.
    """
    Model = env['ir.model'].sudo()
    Access = env['mcp.model.access'].sudo()

    created = 0
    skipped_existing = 0
    skipped_missing = 0

    for model_name, vals in DEFAULT_MODELS_TO_ENABLE:
        model_record = Model.search([('model', '=', model_name)], limit=1)
        if not model_record:
            # El módulo del modelo no está instalado en esta base
            skipped_missing += 1
            _logger.info("MCP setup: modelo '%s' no existe, se omite.", model_name)
            continue

        existing = Access.search([('model_id', '=', model_record.id)], limit=1)
        if existing:
            skipped_existing += 1
            continue

        try:
            Access.create({
                'model_id': model_record.id,
                **vals,
            })
            created += 1
        except Exception as e:
            _logger.warning("MCP setup: no pudo crearse acceso a '%s': %s",
                            model_name, e)

    _logger.info(
        "MCP setup_default_models: creados=%d, ya_existían=%d, no_disponibles=%d",
        created, skipped_existing, skipped_missing,
    )
    return {'created': created, 'existing': skipped_existing, 'missing': skipped_missing}


def setup_default_reports(env):
    """Habilita reportes por defecto en mcp.report.access usando upsert."""
    Access = env['mcp.report.access'].sudo()

    created = 0
    skipped_existing = 0
    skipped_missing = 0

    for xml_id, name, description in DEFAULT_REPORTS_TO_ENABLE:
        try:
            report = env.ref(xml_id, raise_if_not_found=False)
        except Exception:
            report = None

        if not report:
            skipped_missing += 1
            _logger.info("MCP setup: reporte '%s' no existe, se omite.", xml_id)
            continue

        existing = Access.search([('report_id', '=', report.id)], limit=1)
        if existing:
            skipped_existing += 1
            continue

        try:
            Access.create({
                'name': name,
                'report_id': report.id,
                'active': True,
                'description': description,
            })
            created += 1
        except Exception as e:
            _logger.warning("MCP setup: no pudo crearse reporte '%s': %s",
                            xml_id, e)

    _logger.info(
        "MCP setup_default_reports: creados=%d, ya_existían=%d, no_disponibles=%d",
        created, skipped_existing, skipped_missing,
    )
    return {'created': created, 'existing': skipped_existing, 'missing': skipped_missing}
