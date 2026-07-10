# -*- coding: utf-8 -*-
import logging

from . import models

_logger = logging.getLogger(__name__)


# Cuerpos fijos de los templates de cobranza. {{1}}=nombre, {{2}}=total vencido.
_TEMPLATES = [
    {
        'key': 'day0',
        'config_field': 'cobranza_template_day0_id',
        'name': 'Cobranza día 0 — Recordatorio',
        'template_name': 'cobranza_dia_0_recordatorio',
        'report_xmlid': 'cristal_cobranza.action_report_estado_cuenta_full',
        'body': (
            "Hola {{1}}, te escribimos de Química Cristal. Te recordamos que "
            "registrás un saldo vencido de {{2}}. Adjuntamos el estado de cuenta "
            "con el detalle y los comprobantes. Te pedimos regularizarlo a la "
            "brevedad; en el archivo están los datos para el pago. Si ya lo "
            "abonaste, envianos el comprobante. ¡Gracias!"
        ),
    },
    {
        'key': 'day5',
        'config_field': 'cobranza_template_day5_id',
        'name': 'Cobranza día 5 — Seguimiento',
        'template_name': 'cobranza_dia_5_seguimiento',
        'report_xmlid': 'cristal_cobranza.action_report_estado_cuenta',
        'body': (
            "Hola {{1}}, seguimos pendientes de tu saldo vencido de {{2}} con "
            "Química Cristal. Adjuntamos el estado de cuenta actualizado. Te "
            "pedimos abonarlo a la brevedad. Si ya lo abonaste, envianos el "
            "comprobante así lo registramos. ¡Gracias!"
        ),
    },
    {
        'key': 'day10',
        'config_field': 'cobranza_template_day10_id',
        'name': 'Cobranza día 10 — Ultimátum',
        'template_name': 'cobranza_dia_10_ultimatum',
        'report_xmlid': 'cristal_cobranza.action_report_estado_cuenta',
        'body': (
            "Hola {{1}}, tu saldo con Química Cristal continúa vencido: {{2}}. "
            "Este es un último aviso antes de aplicar los recargos por mora "
            "correspondientes. Adjuntamos el estado de cuenta. Te pedimos "
            "regularizar el pago a la brevedad para evitar recargos. Quedamos a "
            "la espera."
        ),
    },
]


def post_init_cobranza(env):
    """Crea (idempotente) los 3 templates de WhatsApp de cobranza en 'draft',
    los vincula a la config y elige una cuenta de WhatsApp por defecto.

    Se hace por código (y no como data XML) para poder asignar la cuenta de
    WhatsApp de forma defensiva y no romper la instalación si ese campo fuese
    obligatorio en esta versión del módulo whatsapp.
    """
    Template = env['whatsapp.template'].sudo()
    config = env['cristal.agent.config'].sudo().search([('active', '=', True)], limit=1)
    if not config:
        config = env['cristal.agent.config'].sudo().search([], limit=1)

    # Cuenta de WhatsApp por defecto: la de la config, si no la primera disponible.
    wa_account = env['whatsapp.account'].sudo()
    if config and config.cobranza_wa_account_id:
        wa_account = config.cobranza_wa_account_id
    else:
        wa_account = env['whatsapp.account'].sudo().search([], limit=1)

    partner_model_id = env['ir.model']._get_id('res.partner')
    config_vals = {}

    for spec in _TEMPLATES:
        try:
            existing = Template.search(
                [('template_name', '=', spec['template_name'])], limit=1)
            if existing:
                tmpl = existing
            else:
                report = env.ref(spec['report_xmlid'], raise_if_not_found=False)
                tmpl = Template.create({
                    'name': spec['name'],
                    'template_name': spec['template_name'],
                    'model_id': partner_model_id,
                    'phone_field': 'mobile',
                    'template_type': 'utility',
                    'lang_code': 'es',
                    'status': 'draft',
                    'header_type': 'document',
                    'report_id': report.id if report else False,
                    'body': spec['body'],
                    'footer_text': 'Química Cristal',
                    'wa_account_id': wa_account.id if wa_account else False,
                    'variable_ids': [
                        (0, 0, {'name': '{{1}}', 'line_type': 'body',
                                'field_type': 'free_text', 'demo_value': 'Juan Pérez'}),
                        (0, 0, {'name': '{{2}}', 'line_type': 'body',
                                'field_type': 'free_text', 'demo_value': '$ 10.000,00'}),
                    ],
                })
                _logger.info("✅ Template de cobranza creado: %s (id=%s)",
                             spec['template_name'], tmpl.id)
            config_vals[spec['config_field']] = tmpl.id
        except Exception as e:  # noqa: BLE001
            _logger.exception("No se pudo crear el template %s: %s",
                              spec['template_name'], e)

    if config:
        if wa_account and not config.cobranza_wa_account_id:
            config_vals['cobranza_wa_account_id'] = wa_account.id
        try:
            config.write(config_vals)
        except Exception as e:  # noqa: BLE001
            _logger.warning("No se pudieron vincular templates a la config: %s", e)
