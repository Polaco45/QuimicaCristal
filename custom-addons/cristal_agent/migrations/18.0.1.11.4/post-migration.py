# -*- coding: utf-8 -*-
"""
Migración 18.0.1.11.4 — Vendedor que cotiza, sin muestras (prompt v4).

- Recarga el prompt mayorista v4 (sin muestras; el bot asesora, dice precios y
  arma cotizaciones en BORRADOR; gancho = 20% OFF primera compra).
- Prende las capacidades de cotización (create_sale_order / generate_quote_pdf)
  y apaga la de muestras.
- Da vuelta la regla "PROHIBIDO pasar precios" en la base de conocimiento.
- Desactiva las entradas de KB referidas a muestras (ya no aplican).
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        _logger.warning("MIGRATION 1.11.4: no hay config activa")
        return

    # 1. Recargar prompt v4
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v4.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v4'})
        _logger.info("✅ MIGRATION 1.11.4: prompt v4 cargado (%s chars)", len(content))
    else:
        _logger.warning("MIGRATION 1.11.4: no se encontró claudio_v4.md")

    # 2. Flags: prender cotizaciones, apagar muestras
    config.write({
        'enable_create_sale_orders': True,
        'enable_generate_quote_pdf': True,
        'enable_confirm_sample': False,
    })

    Knowledge = env['cristal.agent.knowledge']

    # 3. Dar vuelta la regla "PROHIBIDO pasar precios"
    for kb in Knowledge.search([('name', 'ilike', 'PROHIBIDO pasar precios')]):
        kb.write({
            'name': 'Precios y cotizaciones: el bot SÍ cotiza (borrador) — Joaco confirma',
            'content': (
                'ACTUALIZADO (06/2026): el bot PUEDE decir precios del catálogo (Lista '
                'Mayorista, vía search_products) y armar cotizaciones con create_sale_order '
                'en estado BORRADOR. Aplica 20% OFF SOLO en la primera compra '
                '(discount_percent=20). NUNCA inventa precios ni descuentos: salen del '
                'sistema. La venta la CONFIRMA Joaco: cuando el cliente acepta, el bot escala '
                'a Joaco para que la cierre. Sin cuenta corriente. Otros descuentos/plazos '
                'especiales → escalar a Joaco.'),
            'priority': 100,
        })
        _logger.info("✅ MIGRATION 1.11.4: KB de precios actualizada (id=%s)", kb.id)

    # 4. Desactivar KB de muestras (ya no entregamos muestras)
    sample_kb = Knowledge.search([
        '|', ('name', 'ilike', 'muestra'), ('content', 'ilike', 'kit fijo'),
        ('active', '=', True),
    ])
    if sample_kb:
        sample_kb.write({'active': False})
        _logger.info("✅ MIGRATION 1.11.4: %s entradas de KB de muestras desactivadas",
                     len(sample_kb))
