# -*- coding: utf-8 -*-
"""Migración 18.0.1.36.0 — Correcciones de Claudio (conversaciones del 9 al 13/10/2026).

1. 20% de primera compra SOLO Río Cuarto / Las Higueras: se saca el descuento de las
   cotizaciones en borrador de clientes de la ruta / fuera de zona (S06359, S06367 y
   las que haya), respetando la línea de flete (si sin el 20% los productos pasan el
   umbral de envío gratis, el flete se quita). Cada orden tocada queda con una nota
   en el chatter y el listado sale en el log y en el canal interno.
2. KB #59 (20% primera compra): aclara que NO aplica a zona ni fuera de zona.
3. KB #101 (días cerrados / feriados): se reactiva con texto general (los feriados
   ahora salen del calendario del código + config.closed_dates).
4. KB #102 (ruta): fuera de zona = retiro en planta o transporte a cargo del cliente;
   sin 20% en la ruta.
5. Partner 83205 (escribió "Olver"): Holmberg, circuito Sur-Oeste. S06344 queda en
   borrador y sin fecha hasta que se avise la nueva salida.
6. Recarga el prompt v7.
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

KB_FIRST_PURCHASE_ID = 59
KB_FIRST_PURCHASE_CONTENT = """REGLA (Joaco, actualizada 13/10/2026): 20% OFF en la PRIMERA compra — SOLO para clientes de RÍO CUARTO y LAS HIGUERAS.

A QUIÉN SÍ:
- Mayorista de Río Cuarto / Las Higueras (también Banda Norte, Alberdi) que NUNCA compró (o cuya única "compra" es una muestra en $0).

A QUIÉN NO (NUNCA se aplica ni se ofrece ni se menciona):
- Clientes de la RUTA DEL CAMIÓN (Sampacho, Coronel Moldes, Vicuña Mackenna, Holmberg, La Carlota, Adelia María y el resto de los pueblos de los 4 circuitos).
- Clientes de FUERA DE ZONA.
- Clientes que todavía no dijeron su localidad: primero la localidad; el 20% recién se menciona si es de Río Cuarto / Las Higueras.
- Clientes que ya compraron.

EN LA ZONA SÍ SIGUE: la promo de Jabón Ariel / Skip a $600 el litro desde 100 L.

QUÉ HACER (solo Río Cuarto / Las Higueras):
1. Mandarle la lista de precios (generate_pricelist_pdf → send_whatsapp con el PDF adjunto).
2. En el mismo mensaje mencionar el 20% off: "Además, tu primera compra tiene un 20% de descuento."
3. Cotizar con create_sale_order(discount_percent=20). La herramienta valida la zona y el historial: si no corresponde, saca el descuento y avisa.

CONDICIONES:
- El 20% off aplica SOLO a la primera compra real (no a muestras).
- La compra mínima de siempre aplica igual: $50.000 + 20 L granel mínimo."""

KB_CLOSED_ID = 101
KB_CLOSED_CONTENT = """REGLA (Joaco): en feriados nacionales y días no laborables la PLANTA y el REPARTO NO operan: no hay atención presencial, no se puede retirar en planta y no hay entregas.

- El sistema le dice a Claudio en cada mensaje si HOY (o mañana) es feriado o día cerrado y si la planta está abierta en ese momento. Los feriados nacionales 2026-2027 están cargados en el código; los cierres extra (Día del Empleado de Comercio, puentes, cierres puntuales) los carga Joaco en la configuración del agente (campo "Días cerrados").
- Si HOY no se atiende: decir que hoy no atendemos y que respondemos / confirmamos el próximo día hábil (con día y fecha).
- NUNCA confirmes un retiro en planta ni una entrega para un día cerrado. NUNCA digas "hoy estamos abiertos" un feriado.
- Podés seguir cotizando y tomando el pedido, pero la entrega/retiro queda para el próximo día hábil (entregas SOLO por la mañana; el día lo confirma el equipo).
- Si el cliente insiste o hay que coordinar algo puntual de un día cerrado, escalá a Joaco por el canal interno; NO lo resuelvas inventando."""

KB_ROUTE_ID = 102
KB_ROUTE_REPLACEMENTS = [
    ("- FUERA DE LOS 4 CIRCUITOS: se le pasa la lista y los precios, pero NO se ofrecen "
     "condiciones de envío; se marca fuera de zona y se escala a Joaco.",
     "- FUERA DE LOS 4 CIRCUITOS: se le pasa la lista y los precios (sin 20% de primera "
     "compra). Envío: retiro en nuestra planta (San Martín 2350, Río Cuarto) o transporte "
     "a cargo del cliente. NUNCA decir que Joaquín le coordina el envío. Se marca fuera de "
     "zona y se escala a Joaco UNA vez."),
    ("- PRECIO: Lista Mayorista de siempre, sin recargo por zona. No se menciona el IVA.",
     "- PRECIO: Lista Mayorista de siempre, sin recargo por zona. No se menciona el IVA. "
     "En la ruta NO hay 20% de primera compra (es solo para Río Cuarto / Las Higueras); "
     "sí vale la promo Ariel/Skip a $600/L desde 100 L."),
]

OLVER_PARTNER_ID = 83205


def _fmt(v):
    return '${:,.0f}'.format(v or 0).replace(',', '.')


def _remove_zone_discounts(env, config):
    """Saca el 20% de las cotizaciones en borrador de clientes de la ruta / fuera de zona."""
    SaleOrder = env['sale.order'].sudo()
    orders = SaleOrder.search([
        ('state', 'in', ('draft', 'sent')),
        '|', ('partner_id.truck_circuit_id', '!=', False),
        ('partner_id.agent_zone', 'in', ('fuera_zona', 'ruta_camion')),
        ('order_line.discount', '>=', 15),
    ])
    freight_product = config.route_freight_product_id if config else False
    bidon_product = config.bidon_product_id if config else False
    skip_ids = {p.id for p in (freight_product, bidon_product) if p}
    touched = []
    for order in orders:
        lines = order.order_line.filtered(
            lambda l: l.discount >= 15 and l.product_id.id not in skip_ids)
        if not lines:
            continue
        before = order.amount_untaxed
        lines.write({'discount': 0.0})
        note = f"20% quitado de {len(lines)} línea(s)"
        # Flete: si sin el 20% los productos llegan al envío gratis, se quita.
        if freight_product:
            freight_lines = order.order_line.filtered(
                lambda l: l.product_id == freight_product)
            if freight_lines:
                dep = order.route_departure_id
                free_from = config.route_free_shipping_from or 0.0
                if dep and dep.state == 'rescate':
                    free_from = dep.rescue_free_shipping_from or free_from
                products_subtotal = sum(order.order_line.filtered(
                    lambda l: l.product_id.id not in skip_ids).mapped('price_subtotal'))
                if free_from and products_subtotal >= free_from:
                    freight_lines.unlink()
                    note += "; flete quitado (ahora llega al envío sin cargo)"
        order.message_post(body=(
            f"v1.36 — Se quitó el 20% de primera compra: el cliente es de la ruta / fuera "
            f"de zona y el 20% es solo para Río Cuarto / Las Higueras. {note}. Total s/IVA: "
            f"{_fmt(before)} → {_fmt(order.amount_untaxed)}."),
            message_type='comment', subtype_xmlid='mail.mt_note')
        touched.append(f"{order.name} ({order.partner_id.name}, {order.partner_id.city or '-'}): "
                       f"{_fmt(before)} → {_fmt(order.amount_untaxed)} — {note}")
    _logger.info("✅ MIGRATION 1.36.0: 20%% quitado en %s cotizaciones: %s",
                 len(touched), touched)
    channel = config.internal_channel_id if config else False
    if channel and touched:
        channel.sudo().with_context(from_cristal_agent=True).message_post(
            body=("🔧 v1.36 — Saqué el 20% de primera compra (es solo para Río Cuarto / "
                  "Las Higueras) de estas cotizaciones en borrador de clientes de la ruta / "
                  "fuera de zona:<br/>" + "<br/>".join(touched)),
            message_type='comment', subtype_xmlid='mail.mt_comment')
    return touched


def _update_knowledge(env):
    Knowledge = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    kb = Knowledge.browse(KB_FIRST_PURCHASE_ID)
    if kb.exists():
        kb.write({'name': '20% off primera compra — SOLO Río Cuarto / Las Higueras',
                  'content': KB_FIRST_PURCHASE_CONTENT})
        _logger.info("✅ MIGRATION 1.36.0: KB #59 → solo Río Cuarto / Las Higueras")
    kb = Knowledge.browse(KB_CLOSED_ID)
    if kb.exists():
        kb.write({'active': True, 'content': KB_CLOSED_CONTENT})
        _logger.info("✅ MIGRATION 1.36.0: KB #101 reactivada (días cerrados / feriados)")
    else:
        _logger.warning("⚠️ MIGRATION 1.36.0: KB #101 no existe")
    kb = Knowledge.browse(KB_ROUTE_ID)
    if kb.exists():
        content = kb.content or ''
        for old, new in KB_ROUTE_REPLACEMENTS:
            if old in content:
                content = content.replace(old, new)
            else:
                _logger.warning("⚠️ MIGRATION 1.36.0: KB #102 — no encontré '%s…' "
                                "(revisar a mano)", old[:50])
        kb.content = content


def _fix_olver(env):
    """Partner 83205 escribió "Olver" y quedó fuera de zona: es Holmberg (Sur-Oeste)."""
    partner = env['res.partner'].sudo().browse(OLVER_PARTNER_ID)
    if not partner.exists():
        return
    if (partner.city or '').strip().lower() not in ('olver', 'holmberg'):
        _logger.info("MIGRATION 1.36.0: partner %s tiene ciudad '%s'; no lo toco.",
                     OLVER_PARTNER_ID, partner.city)
        return
    info = env['cristal.agent.circuit'].sudo().classify_city('Holmberg')
    if info.get('kind') != 'circuit':
        _logger.warning("⚠️ MIGRATION 1.36.0: no encontré el circuito de Holmberg")
        return
    vals = {'city': 'Holmberg', 'agent_zone': 'ruta_camion',
            'truck_circuit_id': info['circuit'].id}
    fz_tag = env['res.partner.category'].sudo().search([('name', '=', 'Fuera de zona')], limit=1)
    if fz_tag and fz_tag in partner.category_id:
        vals['category_id'] = [(3, fz_tag.id)]
    partner.write(vals)
    _logger.info("✅ MIGRATION 1.36.0: partner %s → Holmberg (%s). S06344 queda en "
                 "borrador sin fecha.", partner.id, info['circuit'].name)


def _reload_prompt(config):
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v7.md')
    if config and os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v7'})
        _logger.info("✅ MIGRATION 1.36.0: prompt v7 recargado (%s chars)", len(content))


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    _remove_zone_discounts(env, config)
    _update_knowledge(env)
    _fix_olver(env)
    _reload_prompt(config)
