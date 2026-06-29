# -*- coding: utf-8 -*-
"""
Migración 18.0.1.19.0 — Ocultar apps "avanzadas" salvo para Sergio y Joaquín.

Joaco quiere despejar el menú superior: que el personal (Alejandra, etc.) no vea
estas apps. Se logra gateando el menú raíz de cada una al grupo
`group_apps_internas` (que tiene solo a Sergio id 2 y Joaquín id 18).

Apps a ocultar: Aplicaciones, Eventos, Empleados, Sitio web, Planeación,
Suscripciones e Información (Knowledge).

Se buscan los menús de nivel superior por NOMBRE (es + en) para no depender de
xmlids internos que cambian entre versiones de Odoo. Lo que no matchea se ignora
(no rompe nada). Es reversible: sacando el groups_id del menú vuelve a verse.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

# Nombres de los menús raíz a ocultar (es + en, en minúscula).
TARGET_NAMES = {
    'aplicaciones', 'apps',
    'eventos', 'events',
    'empleados', 'employees',
    'sitio web', 'website',
    'planeación', 'planeacion', 'planning',
    'suscripciones', 'subscriptions',
    'información', 'informacion', 'knowledge', 'conocimiento',
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    group = env.ref('cristal_agent.group_apps_internas', raise_if_not_found=False)
    if not group:
        _logger.warning("MIGRATION 1.19.0: no existe group_apps_internas")
        return

    top_menus = env['ir.ui.menu'].search([('parent_id', '=', False)])
    to_gate = top_menus.filtered(
        lambda m: (m.name or '').strip().lower() in TARGET_NAMES)

    if not to_gate:
        _logger.warning("MIGRATION 1.19.0: no se encontraron menús target por nombre")
        return

    to_gate.write({'groups_id': [(6, 0, [group.id])]})
    _logger.info(
        "✅ MIGRATION 1.19.0: %s apps ocultadas (solo Sergio/Joaquín): %s",
        len(to_gate), ', '.join(to_gate.mapped('name')))
