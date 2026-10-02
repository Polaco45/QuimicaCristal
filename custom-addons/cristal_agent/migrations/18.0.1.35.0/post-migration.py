# -*- coding: utf-8 -*-
"""Migración 18.0.1.35.0 — La ruta del camión pasa de JUEVES a MIÉRCOLES.

Joaco ya cambió por MCP la config (rc_no_delivery_weekday=2, cierre de preventa
lunes 18 h) y las plantillas 252-257. Acá:
1. Circuitos: weekday = miércoles y primeras salidas 14/10, 21/10, 28/10 y 4/11.
2. Salidas: se generan las de los miércoles (12 semanas). Las salidas futuras de
   JUEVES: las cotizaciones en borrador se pasan al miércoles anterior (con su
   commitment_date recalculado); si la salida queda sin pedidos se borra; si tiene
   pedidos confirmados NO se borra y se avisa a Joaco por el canal interno.
3. KB #102 → "Ruta camión miércoles" (texto nuevo); KB #89: reparto en Río Cuarto
   sin miércoles.
4. Recarga el prompt v7 (jueves/martes → miércoles/lunes).
"""
import logging
import os
from datetime import date, timedelta

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

WEDNESDAY = 2
THURSDAY = 3
FIRST_DATES = {
    'cristal_agent.circuit_sur_oeste': date(2026, 10, 14),
    'cristal_agent.circuit_norte': date(2026, 10, 21),
    'cristal_agent.circuit_este': date(2026, 10, 28),
    'cristal_agent.circuit_sur_este': date(2026, 11, 4),
}

KB_ROUTE_ID = 102
KB_ROUTE_NAME = "Ruta camión miércoles"
KB_ROUTE_CONTENT = """RUTA DEL CAMIÓN MAYORISTA (desde el miércoles 14/10/2026)
- Sale UN camión por semana, los MIÉRCOLES, a uno de 4 circuitos que rotan: Sur-Oeste → Norte → Este → Sur-Este. Cada pueblo tiene pasada cada 4 semanas.
- Circuitos y localidades:
 • Sur-Oeste: Holmberg, Santa Catalina, Las Vertientes, Sampacho, Suco, Chaján y Achiras (desvío opcional), Coronel Moldes, Vicuña Mackenna, Tosquita, Malena.
 • Norte: Espinillo, Coronel Baigorria, Alcira Gigena, Elena, Berrotarán, General Cabrera, General Deheza, Las Perdices, Dalmacio Vélez, Carnerillo, Chucul.
 • Este: Las Acequias, Reducción, Alejandro Roca, La Carlota, Chazón, Ucacha, Bengolea, Olaeta, Charras.
 • Sur-Este: San Basilio, Adelia María, Monte de los Gauchos.
- FECHA Y CIERRE: los da SIEMPRE get_route_info, textual. La salida es el MIÉRCOLES; la preventa cierra el LUNES previo a las 18 h. Si la salida está en RESCATE (Plan B), el aviso de rescate sale el lunes y se puede confirmar hasta el MARTES a las 12 h. NUNCA prometer otra fecha.
- PRECIO: Lista Mayorista de siempre, sin recargo por zona. No se menciona el IVA.
- MÍNIMO EN RUTA: $75.000 en productos (el flete y los bidones NO cuentan). FLETE: $9.000 si los productos no llegan a $99.000; desde $99.000 el envío es sin cargo. RESCATE (Plan B): envío sin cargo desde $75.000 + un producto de cortesía.
- RECAMBIO DE BIDONES: el granel va en bidones de 20 L; por cada bidón lleno el cliente entrega un bidón vacío de 20 L con tapa. Si se lo enviamos, los vacíos los entrega en el momento de la entrega (no tiene que traer nada); si retira en planta, los lleva al retirar. Si no tiene vacíos para canjear, cada bidón nuevo sale $3.500. Decirlo SIEMPRE.
- COBRO: transferencia anticipada o efectivo contra entrega. Sin cuenta corriente.
- RÍO CUARTO (y Las Higueras, Banda Norte, Alberdi): reparto normal, de lunes a viernes SOLO por la mañana y NUNCA los MIÉRCOLES (ese día sale el camión de la ruta). El RETIRO en planta el miércoles SÍ se puede, en el horario oficial. Pedidos grandes o especiales: consultar a Joaco antes de comprometer la entrega.
- FUERA DE LOS 4 CIRCUITOS: se le pasa la lista y los precios, pero NO se ofrecen condiciones de envío; se marca fuera de zona y se escala a Joaco."""

KB_PLANT_ID = 89
KB_PLANT_REPLACEMENTS = [
    ("SOLO por la mañana y NUNCA los jueves (ese día sale el camión de la ruta).",
     "SOLO por la mañana y NUNCA los miércoles (ese día sale el camión de la ruta)."),
    ("aunque los jueves no hay reparto en Río Cuarto, la planta SÍ abre el jueves "
     "para retiros",
     "aunque los miércoles no hay reparto en Río Cuarto, la planta SÍ abre el "
     "miércoles para retiros"),
]


def _move_circuits(env):
    for xmlid, first in FIRST_DATES.items():
        circuit = env.ref(xmlid, raise_if_not_found=False)
        if not circuit:
            _logger.warning("⚠️ MIGRATION 1.35.0: no existe %s", xmlid)
            continue
        circuit.write({'weekday': str(WEDNESDAY), 'first_departure_date': first})
        _logger.info("✅ MIGRATION 1.35.0: %s → miércoles, 1ra salida %s",
                     circuit.name, first)


def _move_departures(env, config):
    Dep = env['cristal.agent.route.departure'].sudo()
    created = Dep.generate_upcoming(weeks=12)
    _logger.info("✅ MIGRATION 1.35.0: %s salidas de miércoles generadas", created)

    today = Dep._local_today()
    old = Dep.search([('date', '>=', today)]).filtered(
        lambda d: d.date.weekday() == THURSDAY)
    deleted, kept = [], []
    for dep in old:
        wed_date = dep.date - timedelta(days=1)
        new = Dep.search([('circuit_id', '=', dep.circuit_id.id),
                          ('date', '=', wed_date)], limit=1)
        if not new:
            new = Dep.create({'circuit_id': dep.circuit_id.id, 'date': wed_date})
        # Lo que se haya configurado a mano en la salida vieja pasa a la nueva.
        new.write({
            'state': dep.state if dep.state in ('preventa', 'rescate') else new.state,
            'rescue_free_shipping_from': dep.rescue_free_shipping_from,
            'courtesy_product_id': dep.courtesy_product_id.id or new.courtesy_product_id.id,
        })
        # Cotizaciones en borrador → al miércoles, con la fecha de entrega nueva.
        drafts = dep.order_ids.filtered(lambda o: o.state in ('draft', 'sent'))
        if drafts:
            drafts.write({'route_departure_id': new.id,
                          'commitment_date': new.get_commitment_datetime()})
            _logger.info("✅ MIGRATION 1.35.0: %s cotizaciones de %s → %s (%s)",
                         len(drafts), dep.name, new.name, ', '.join(drafts.mapped('name')))
        live = dep.order_ids.filtered(lambda o: o.state != 'cancel')
        if live:
            kept.append(f"{dep.name}: {', '.join(live.mapped('name'))}")
            continue
        deleted.append(dep.name)
        dep.unlink()

    _logger.info("✅ MIGRATION 1.35.0: salidas de jueves borradas (%s): %s",
                 len(deleted), deleted)
    if kept:
        msg = ("🚚 Cambio de la ruta a MIÉRCOLES: estas salidas de JUEVES tienen pedidos "
               "confirmados y NO las borré. Revisalas (mové los pedidos al miércoles y "
               "borrá la salida, o dejala si ese viaje se hace igual): "
               + "; ".join(kept))
        _logger.warning("⚠️ MIGRATION 1.35.0: %s", msg)
        channel = config.internal_channel_id if config else False
        if channel:
            channel.sudo().message_post(body=msg, message_type='comment',
                                        subtype_xmlid='mail.mt_comment')


def _update_knowledge(env):
    Knowledge = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    kb = Knowledge.browse(KB_ROUTE_ID)
    if kb.exists():
        kb.write({'name': KB_ROUTE_NAME, 'content': KB_ROUTE_CONTENT})
        _logger.info("✅ MIGRATION 1.35.0: KB #%s → %s", KB_ROUTE_ID, KB_ROUTE_NAME)
    else:
        _logger.warning("⚠️ MIGRATION 1.35.0: KB #%s no existe", KB_ROUTE_ID)

    kb = Knowledge.browse(KB_PLANT_ID)
    if kb.exists():
        content = kb.content or ''
        for old, new in KB_PLANT_REPLACEMENTS:
            if old in content:
                content = content.replace(old, new)
            else:
                _logger.warning("⚠️ MIGRATION 1.35.0: KB #%s — no encontré '%s…' "
                                "(revisar a mano)", KB_PLANT_ID, old[:40])
        kb.content = content


def _reload_prompt(config):
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v7.md')
    if config and os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v7'})
        _logger.info("✅ MIGRATION 1.35.0: prompt v7 recargado (%s chars)", len(content))


def _ensure_config(config):
    """En prod Joaco ya lo cambió por MCP; en staging (copia vieja) no. Solo se
    tocan los valores que siguen en el esquema de jueves."""
    if not config:
        return
    vals = {}
    if config.rc_no_delivery_weekday == THURSDAY:
        vals['rc_no_delivery_weekday'] = WEDNESDAY
    if config.route_preventa_cutoff_weekday == 1:  # martes → lunes
        vals['route_preventa_cutoff_weekday'] = 0
    if vals:
        config.write(vals)
        _logger.info("✅ MIGRATION 1.35.0: config ajustada %s", vals)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    _ensure_config(config)
    _move_circuits(env)
    _move_departures(env, config)
    _update_knowledge(env)
    _reload_prompt(config)
