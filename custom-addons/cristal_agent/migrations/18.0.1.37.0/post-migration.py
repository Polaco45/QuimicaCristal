# -*- coding: utf-8 -*-
"""Migración 18.0.1.37.0 — Envío sin cargo de la ruta desde config.route_free_shipping_from.

Joaco (15/10/2026): el envío sin cargo de la ruta pasa a $150.000 (ya cargado en
config.route_free_shipping_from). Base del umbral: subtotal sin IVA de TODAS las
líneas excepto el flete (los bidones cuentan).

1. KB #102: la línea del mínimo/flete se reescribe con el monto de la config y la base.
2. KB #58 y #64 (20% de primera compra "a todos los mayoristas", campañas de junio):
   se archivan; la regla vigente es la KB #59 (solo Río Cuarto / Las Higueras).
3. "Envío sin cargo acordado" en S06319 (Vero Machuca) y S06381 (Marina Duarte).
4. Partner 83205 ("Olver") = Holmberg, Sur-Oeste; su cotización S06344 pasa a la
   salida Sur-Oeste del 21/10, con flete si corresponde.
5. Recarga el prompt v7 (upsell al umbral de envío sin cargo).
"""
import logging
import os
import re
from datetime import date

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

KB_ROUTE_ID = 102
KB_ARCHIVE = {58: "20% a todos los mayoristas (regla de junio, reemplazada por la KB #59)",
              64: "campaña del 10/06 con 20% a todos y precios viejos (reemplazada por la KB #59)"}
GRANTED_ORDERS = ('S06319', 'S06381')
OLVER_PARTNER_ID = 83205
OLVER_ORDER = 'S06344'
OLVER_DEPARTURE_DATE = date(2026, 10, 21)


def _money(v):
    return '$' + '{:,.0f}'.format(v or 0).replace(',', '.')


def _kb_route(env, config):
    kb = env['cristal.agent.knowledge'].sudo().with_context(active_test=False).browse(KB_ROUTE_ID)
    if not kb.exists():
        _logger.warning("⚠️ MIGRATION 1.37.0: KB #102 no existe")
        return
    line = (f"- MÍNIMO EN RUTA: {_money(config.route_min_order)} en productos (el flete y los "
            f"bidones NO cuentan). ENVÍO SIN CARGO desde {_money(config.route_free_shipping_from)} "
            f"(monto vigente de la configuración; lo da get_route_info): se mide sobre el "
            f"subtotal sin IVA de TODO el pedido —bidones nuevos incluidos— sin contar el "
            f"flete. Debajo de ese monto, FLETE {_money(config.route_freight_amount)}. Si "
            f"Joaquín le acordó el envío sin cargo a un cliente, no se cobra flete. RESCATE "
            f"(Plan B): envío sin cargo desde el monto de rescate de la salida + un producto "
            f"de cortesía.")
    content, n = re.subn(r'^- MÍNIMO EN RUTA:.*$', line, kb.content or '', flags=re.M)
    if n:
        kb.content = content
        _logger.info("✅ MIGRATION 1.37.0: KB #102 — línea de mínimo/envío sin cargo actualizada")
    else:
        _logger.warning("⚠️ MIGRATION 1.37.0: KB #102 sin línea 'MÍNIMO EN RUTA' (revisar a mano)")


def _archive_kb(env):
    Knowledge = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    for kb_id, why in KB_ARCHIVE.items():
        kb = Knowledge.browse(kb_id)
        if kb.exists() and kb.active:
            kb.active = False
            _logger.info("✅ MIGRATION 1.37.0: KB #%s archivada — %s", kb_id, why)


def _grant_free_shipping(env):
    SaleOrder = env['sale.order'].sudo()
    for name in GRANTED_ORDERS:
        order = SaleOrder.search([('name', '=', name)], limit=1)
        if not order:
            _logger.warning("⚠️ MIGRATION 1.37.0: no existe %s", name)
            continue
        order.write({'route_free_shipping_granted': True})  # saca el flete si lo tenía
        order.message_post(body="v1.37 — Envío sin cargo acordado (pedido de Joaco): esta "
                                "cotización no lleva flete de ruta.",
                           message_type='comment', subtype_xmlid='mail.mt_note')
        _logger.info("✅ MIGRATION 1.37.0: %s → envío sin cargo acordado", name)


def _fix_olver(env, config):
    partner = env['res.partner'].sudo().browse(OLVER_PARTNER_ID)
    circuit = env['cristal.agent.circuit'].sudo().resolve_circuit('Holmberg')
    if partner.exists() and circuit:
        vals = {}
        if partner.city != 'Holmberg':
            vals['city'] = 'Holmberg'
        if partner.truck_circuit_id != circuit:
            vals['truck_circuit_id'] = circuit.id
        if partner.agent_zone != 'ruta_camion':
            vals['agent_zone'] = 'ruta_camion'
        if vals:
            partner.write(vals)
    order = env['sale.order'].sudo().search([('name', '=', OLVER_ORDER)], limit=1)
    if not (order and circuit) or order.state not in ('draft', 'sent'):
        _logger.warning("⚠️ MIGRATION 1.37.0: %s no está en borrador o no hay circuito", OLVER_ORDER)
        return
    dep = env['cristal.agent.route.departure'].sudo().search([
        ('circuit_id', '=', circuit.id), ('date', '=', OLVER_DEPARTURE_DATE)], limit=1)
    if not dep:
        _logger.warning("⚠️ MIGRATION 1.37.0: no hay salida %s el %s", circuit.name,
                        OLVER_DEPARTURE_DATE)
        return
    free_from = (dep.rescue_free_shipping_from if dep.state == 'rescate'
                 else config.route_free_shipping_from)
    freight, base = order._cristal_apply_route_freight(config, free_from)
    tag = env['crm.tag'].sudo().search([('name', '=', f"Ruta {circuit.name}")], limit=1)
    vals = {'route_departure_id': dep.id, 'commitment_date': dep.get_commitment_datetime()}
    if tag:
        vals['tag_ids'] = [(4, tag.id)]
    order.write(vals)
    order.message_post(body=(f"v1.37 — Cliente de Holmberg (escribió 'Olver'): asignada a la "
                             f"salida {dep.name}. Pedido sin IVA {_money(base)} → "
                             f"{'flete ' + _money(freight) if freight else 'envío sin cargo'}."),
                       message_type='comment', subtype_xmlid='mail.mt_note')
    _logger.info("✅ MIGRATION 1.37.0: %s → salida %s, base %s, flete %s",
                 OLVER_ORDER, dep.name, base, freight)


def _reload_prompt(config):
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v7.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v7'})
        _logger.info("✅ MIGRATION 1.37.0: prompt v7 recargado (%s chars)", len(content))


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        return
    _kb_route(env, config)
    _archive_kb(env)
    _grant_free_shipping(env)
    _fix_olver(env, config)
    _reload_prompt(config)
