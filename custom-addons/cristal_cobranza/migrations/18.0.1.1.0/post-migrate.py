# -*- coding: utf-8 -*-
"""Migración: corrige las variables de las plantillas de WhatsApp de cobranza,
de 'texto libre' (que pega el valor de ejemplo) a 'Campo' (autocompletado desde
el registro). Corre al ACTUALIZAR el módulo, para arreglar las plantillas que ya
fueron creadas por el post_init_hook en una versión anterior.

Solo toca plantillas en borrador (no una ya aprobada por Meta).
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

_TEMPLATE_NAMES = [
    'cobranza_dia_0_recordatorio',
    'cobranza_dia_5_seguimiento',
    'cobranza_dia_10_ultimatum',
]


def _var_cmds():
    return [
        (5, 0, 0),  # limpia las variables previas (free_text)
        (0, 0, {'name': '{{1}}', 'line_type': 'body',
                'field_type': 'field', 'field_name': 'name',
                'demo_value': 'Juan Pérez'}),
        (0, 0, {'name': '{{2}}', 'line_type': 'body',
                'field_type': 'field',
                'field_name': 'cobranza_total_vencido_display',
                'demo_value': '$ 10.000,00'}),
    ]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Template = env['whatsapp.template'].sudo()
    for tname in _TEMPLATE_NAMES:
        tmpl = Template.search([('template_name', '=', tname)], limit=1)
        if not tmpl:
            continue
        if tmpl.status != 'draft':
            _logger.info("↷ %s no está en borrador (status=%s); no toco sus variables.",
                         tname, tmpl.status)
            continue
        try:
            tmpl.write({'variable_ids': _var_cmds()})
            _logger.info("🩹 Variables de '%s' migradas a tipo Campo.", tname)
        except Exception as e:  # noqa: BLE001
            _logger.exception("No se pudo migrar las variables de '%s': %s", tname, e)
