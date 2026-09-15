# -*- coding: utf-8 -*-
"""Migración: desvincula el report_id de las plantillas de WhatsApp de cobranza.

A partir de esta versión el documento que viaja por WhatsApp (estado de cuenta +
facturas fiscales reales con CAE) se adjunta al enviar vía composer.attachment_id,
no se regenera desde template.report_id (que apuntaba a un reporte que embebía las
facturas con un t-call genérico → salían sin CAE y en inglés).

Quitar el report_id no afecta la aprobación de Meta (el header sigue siendo
'document'); solo cambia de dónde sale el documento en cada envío.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

_TEMPLATE_NAMES = [
    'cobranza_dia_0_recordatorio',
    'cobranza_dia_5_seguimiento',
    'cobranza_dia_10_ultimatum',
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Template = env['whatsapp.template'].sudo()
    for tname in _TEMPLATE_NAMES:
        tmpl = Template.search([('template_name', '=', tname)], limit=1)
        if tmpl and tmpl.report_id:
            try:
                tmpl.write({'report_id': False})
                _logger.info("🧾 Desvinculado report_id de la plantilla '%s'.", tname)
            except Exception as e:  # noqa: BLE001
                _logger.exception("No se pudo desvincular report_id de '%s': %s", tname, e)
