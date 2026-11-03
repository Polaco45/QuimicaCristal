# -*- coding: utf-8 -*-
"""Migración 18.0.1.54.0 — La ruta del camión vuelve a salir los JUEVES (v1.35-1.53: miércoles).

Joaco, 03/11/2026: "a partir de ahora la zona se hace los jueves, incluyendo esta zona
Norte de esta semana". Acá:
1. Config: Río Cuarto sin reparto = jueves (3); cierre de preventa miércoles (2) 18 h.
2. Circuitos: weekday = jueves; first_departure_date corrido un día.
3. Salidas: cada salida futura que cae miércoles pasa al jueves siguiente (misma
   salida, mismos pedidos: solo cambia la fecha) y se recalcula el commitment_date de
   sus cotizaciones y pedidos. Después se generan las que falten (12 semanas).
4. KB #102 → "Ruta camión jueves"; KB #89: reparto en Río Cuarto sin jueves.
5. Prompt v10 (= v9 con jueves) si la config estaba en v9.
"""
import logging
import os
from datetime import timedelta

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

WEDNESDAY = 2
THURSDAY = 3

KB_ROUTE_ID = 102
KB_ROUTE_REPLACEMENTS = [
    ("Ruta camión miércoles", "Ruta camión jueves"),
    ("desde el miércoles 21/10/2026", "desde el jueves 05/11/2026"),
    ("desde el miércoles 14/10/2026", "desde el jueves 05/11/2026"),
    ("los MIÉRCOLES,", "los JUEVES,"),
    ("La salida es el MIÉRCOLES; la preventa cierra el LUNES previo a las 18 h.",
     "La salida es el JUEVES; la preventa cierra el MIÉRCOLES previo a las 18 h."),
    ("el aviso de rescate sale el lunes y se puede confirmar hasta el MARTES a las 12 h",
     "el aviso de rescate sale el martes y se puede confirmar hasta el MIÉRCOLES a las 12 h"),
    ("NUNCA los MIÉRCOLES (ese día sale el camión de la ruta)",
     "NUNCA los JUEVES (ese día sale el camión de la ruta)"),
    ("El RETIRO en planta el miércoles SÍ se puede", "El RETIRO en planta el jueves SÍ se puede"),
    # Texto que Joaco retocó a mano en prod (corregido por RPC el 03/11/2026; queda por si
    # la KB vuelve a ese texto en staging):
    ("la preventa cierra el lunes 18 h previo al miércoles; si la salida está en rescate, el martes 12 h",
     "la preventa cierra el miércoles 18 h previo al jueves; si la salida está en rescate, el miércoles 12 h"),
    ("NUNCA los miércoles (el RETIRO en planta el miércoles SÍ se puede",
     "NUNCA los jueves (el RETIRO en planta el jueves SÍ se puede"),
]
KB_PLANT_ID = 89
KB_PLANT_REPLACEMENTS = [
    ("NUNCA los miércoles (ese día sale el camión de la ruta)",
     "NUNCA los jueves (ese día sale el camión de la ruta)"),
    ("aunque los miércoles no hay reparto en Río Cuarto, la planta SÍ abre el miércoles para retiros",
     "aunque los jueves no hay reparto en Río Cuarto, la planta SÍ abre el jueves para retiros"),
]


def _config(env, config):
    if not config:
        return
    vals = {}
    if config.rc_no_delivery_weekday != THURSDAY:
        vals['rc_no_delivery_weekday'] = THURSDAY
    if config.route_preventa_cutoff_weekday != 2:
        vals['route_preventa_cutoff_weekday'] = 2
    if vals:
        config.write(vals)
        _logger.info("✅ MIGRATION 1.54.0: config %s", vals)


def _circuits(env):
    for circuit in env['cristal.agent.circuit'].sudo().with_context(active_test=False).search([]):
        vals = {'weekday': str(THURSDAY)}
        first = circuit.first_departure_date
        if first and first.weekday() == WEDNESDAY:
            vals['first_departure_date'] = first + timedelta(days=1)
        circuit.write(vals)
        _logger.info("✅ MIGRATION 1.54.0: circuito %s → jueves (1ra salida %s)",
                     circuit.name, vals.get('first_departure_date', first))


def _departures(env):
    Dep = env['cristal.agent.route.departure'].sudo()
    today = Dep._local_today()
    moved = []
    for dep in Dep.search([('date', '>=', today)], order='date'):
        if dep.date.weekday() != WEDNESDAY:
            continue
        new_date = dep.date + timedelta(days=1)
        clash = Dep.search([('circuit_id', '=', dep.circuit_id.id), ('date', '=', new_date),
                            ('id', '!=', dep.id)], limit=1)
        if clash and clash.order_ids:
            _logger.warning("⚠️ MIGRATION 1.54.0: %s no se mueve: ya existe %s con pedidos", dep.name, clash.name)
            continue
        if clash:
            clash.unlink()
        old_name = dep.name
        original = dep.original_date
        dep.write({'date': new_date})
        # Cambio de esquema, no una postergación: no queda marcada como reprogramada.
        dep.original_date = original
        orders = dep.order_ids.filtered(lambda o: o.state != 'cancel')
        if orders:
            orders.write({'commitment_date': dep.get_commitment_datetime()})
        moved.append(f"{old_name} → {dep.name} ({len(orders)} pedidos)")
    _logger.info("✅ MIGRATION 1.54.0: salidas movidas al jueves: %s", moved)
    created = Dep.generate_upcoming(weeks=12)
    _logger.info("✅ MIGRATION 1.54.0: %s salidas nuevas generadas", created)
    return moved


def _knowledge(env):
    Knowledge = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    for kb_id, replacements in ((KB_ROUTE_ID, KB_ROUTE_REPLACEMENTS),
                                (KB_PLANT_ID, KB_PLANT_REPLACEMENTS)):
        kb = Knowledge.browse(kb_id)
        if not kb.exists():
            _logger.warning("⚠️ MIGRATION 1.54.0: KB #%s no existe", kb_id)
            continue
        name, content = kb.name or '', kb.content or ''
        for old, new in replacements:
            if old in name:
                name = name.replace(old, new)
            if old in content:
                content = content.replace(old, new)
        kb.write({'name': name, 'content': content})
        if 'miércoles' in content.lower():
            _logger.warning("⚠️ MIGRATION 1.54.0: KB #%s todavía menciona 'miércoles' (revisar a mano)", kb_id)
        _logger.info("✅ MIGRATION 1.54.0: KB #%s actualizada (%s)", kb_id, name)


def _prompt(config):
    if not config or (config.prompt_version or '') != 'claudio_v9':
        _logger.info("MIGRATION 1.54.0: prompt_version=%s, no se recarga", config and config.prompt_version)
        return
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        'data', 'prompts', 'claudio_v10.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v10'})
        _logger.info("✅ MIGRATION 1.54.0: prompt v10 cargado (%s chars)", len(content))


def _notify(config, moved):
    channel = config.internal_channel_id if config else False
    if not channel:
        return
    body = ("🚚 <b>La ruta del camión pasa a los JUEVES</b> (v1.54). Río Cuarto sin reparto los jueves; "
            "preventa hasta el miércoles 18 h; rescate hasta el miércoles 12 h. Salidas movidas: "
            + ("; ".join(moved) if moved else "ninguna") +
            ". Revisar las plantillas de WhatsApp ruta_* (dicen miércoles/lunes/martes).")
    channel.sudo().with_context(from_cristal_agent=True).message_post(
        body=body, message_type='comment', subtype_xmlid='mail.mt_comment')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    _config(env, config)
    _circuits(env)
    moved = _departures(env)
    _knowledge(env)
    _prompt(config)
    _notify(config, moved)
