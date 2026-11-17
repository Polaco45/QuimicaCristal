# -*- coding: utf-8 -*-
"""Migración 18.0.1.74.0 — Reestructura de la ruta del camión (Joaco, 17/11/2026).

Quedan solo NORTE y SUR-OESTE, alternando semana por medio (cada pueblo, cada 15 días).
ESTE y SUR-ESTE quedan PAUSADOS hasta nuevo aviso: retiro en el local con comisionista o
transporte propio, a precio mayorista, sin mínimo ni flete.

Calendario: Norte jue 26/11 · Sur-Oeste jue 03/12 · Norte jue 10/12 · Sur-Oeste jue 17/12 ·
Norte mié 23/12 (se adelanta por Nochebuena). Enero lo define Joaco: no se generan salidas
después del 23/12 (parámetro cristal_agent.route_no_departures_after).

Los pedidos de las zonas pausadas ya los canceló y avisó otro chat el 17/11 (S07085,
S07155, S07061, S07128, S07083). Acá solo se ordenan circuitos y salidas.
"""
import logging
from datetime import date, timedelta

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

CALENDAR = {
    'Norte': [date(2026, 11, 26), date(2026, 12, 10), date(2026, 12, 23)],
    'Sur-Oeste': [date(2026, 12, 3), date(2026, 12, 17)],
}
PAUSED = ('Este', 'Sur-Este')
NO_DEPARTURES_AFTER = '2026-12-23'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Circuit = env['cristal.agent.circuit'].with_context(active_test=False)
    Dep = env['cristal.agent.route.departure']
    by_name = {c.name: c for c in Circuit.search([])}
    if not all(n in by_name for n in CALENDAR):
        _logger.warning("MIGRATION 1.74.0: faltan los circuitos Norte / Sur-Oeste; no toco la ruta.")
        return

    for name in PAUSED:
        if name in by_name:
            by_name[name].paused = True
    for name, dates in CALENDAR.items():
        by_name[name].write({'paused': False, 'first_departure_date': dates[0]})
    env['ir.config_parameter'].set_param(
        'cristal_agent.route_no_departures_after', NO_DEPARTURES_AFTER)

    keep = {(by_name[n].id, d) for n, dates in CALENDAR.items() for d in dates}
    today = date.today()
    removed, held = [], []
    for dep in Dep.search([('date', '>=', today)]):
        if (dep.circuit_id.id, dep.date) in keep:
            continue
        live = dep.order_ids.filtered(lambda o: o.state != 'cancel')
        if live:
            # Con pedidos vivos no se borra: queda postergada (no toma pedidos ni dispara
            # avisos) y se informa para que alguien lo resuelva con el cliente.
            held.append(f"{dep.name} ({', '.join(live.mapped('name'))})")
            dep.with_context(no_reschedule_notice=True).write({'state': 'postergada'})
            continue
        name = dep.name
        try:
            with cr.savepoint():
                dep.unlink()
            removed.append(name)
        except Exception as e:  # noqa: BLE001 — algo la referencia: queda postergada
            _logger.warning("MIGRATION 1.74.0: no pude borrar %s (%s); la postergo.", name, e)
            dep.with_context(no_reschedule_notice=True).write({'state': 'postergada'})

    created = []
    for name, dates in CALENDAR.items():
        circuit = by_name[name]
        for d in dates:
            if d < today:
                continue
            # Día habitual de esa semana (jueves). Si la salida va otro día (Norte del mié
            # 23/12), queda anotada como adelantada: original_date = el jueves.
            regular = d + timedelta(days=int(circuit.weekday or 3) - d.weekday())
            dep = Dep.search([('circuit_id', '=', circuit.id), ('date', '=', d)], limit=1)
            if not dep:
                dep = Dep.create({'circuit_id': circuit.id, 'date': d, 'state': 'preventa'})
                created.append(dep.name)
            elif dep.state == 'postergada':
                dep.state = 'preventa'
            if regular != d and not dep.original_date:
                dep.with_context(no_reschedule_notice=True).write({'original_date': regular})

    _logger.info("✅ MIGRATION 1.74.0: pausados %s · salidas creadas %s · borradas %s · "
                 "con pedidos (postergadas) %s", PAUSED, created, removed, held)
    if held:
        config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
        if config and config.internal_channel_id:
            config.internal_channel_id.with_context(from_cristal_agent=True).message_post(
                body=("🚚 Reestructura de la ruta (solo Norte y Sur-Oeste): estas salidas "
                      "quedaron fuera del calendario pero tienen pedidos sin cancelar: "
                      + "; ".join(held) + ". Revisar con cada cliente."),
                message_type='comment', subtype_xmlid='mail.mt_comment')
