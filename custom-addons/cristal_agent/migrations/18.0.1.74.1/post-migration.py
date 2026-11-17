# -*- coding: utf-8 -*-
"""Migración 18.0.1.74.1 — Joaco (17/11/2026): el camión sale UN jueves cada DOS semanas,
alternando Sur-Oeste y Norte (cada pueblo, cada 4 semanas). Calendario: Sur-Oeste jue 26/11 ·
Norte jue 10/12 · Sur-Oeste mié 23/12 (se adelanta por Nochebuena). Las salidas ya se
reordenaron a mano en producción el 17/11; acá queda el parámetro de la rotación y las
primeras salidas de cada circuito (idempotente)."""
import logging
from datetime import date

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

FIRST = {'Sur-Oeste': date(2026, 11, 26), 'Norte': date(2026, 12, 10)}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ir.config_parameter'].set_param('cristal_agent.route_weeks_between_departures', '2')
    Circuit = env['cristal.agent.circuit'].with_context(active_test=False)
    for name, first in FIRST.items():
        circuit = Circuit.search([('name', '=', name)], limit=1)
        if circuit and circuit.first_departure_date != first:
            circuit.first_departure_date = first
    _logger.info("✅ MIGRATION 1.74.1: una salida cada 2 semanas (Sur-Oeste 26/11, Norte 10/12).")
