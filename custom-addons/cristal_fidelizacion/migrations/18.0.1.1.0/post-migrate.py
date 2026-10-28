# -*- coding: utf-8 -*-
"""Lealtad Cristal con premios Crilimp (28/10/2026; Joaco: "elegilos vos con criterio").

Se sigue sumando igual (2 puntos cada $100). Premios: el primero a ~$30.000 de compras y
cada premio cuesta entre 1 % y 3 % de lo comprado para llegar a él. Se quedan el envío
gratis y el 10 %. Salen el 5 %, el detergente de 1 lt y los combos viejos. El cupón de 5 %
en la próxima compra (uso 1-4 %) deja de emitirse: lo reemplazan los puntos.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# (puntos, product.product id, descripción) — puntos ≈ compras / 50
PRODUCT_REWARDS = [
    (600, 11766, 'Limpiador Desodorante Crilimp 900cc de regalo'),      # ~$30.000
    (1200, 11960, 'Lavandina Doble Rendimiento Crilimp 5 lts de regalo'),  # ~$60.000
    (2500, 6335, 'Detergente Crilimp 5 lts de regalo'),                  # ~$125.000
    (3500, 5433, 'Jabón Premium Crilimp 5 lts de regalo'),               # ~$175.000
]
KEEP_TYPES = ('shipping',)
KEEP_DISCOUNT_PERCENT = 10.0
NEXT_ORDER_5_PCT = '5%off en tu Próxima Compra'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    program = env['loyalty.program'].search(
        [('name', '=', 'Lealtad Cristal'), ('program_type', '=', 'loyalty')], limit=1)
    if not program:
        _logger.warning("lealtad: no encontré 'Lealtad Cristal'")
        return
    Product = env['product.product']
    for reward in program.reward_ids:
        keep = reward.reward_type in KEEP_TYPES or (
            reward.reward_type == 'discount' and reward.discount == KEEP_DISCOUNT_PERCENT)
        if not keep:
            reward.active = False
    for points, product_id, description in PRODUCT_REWARDS:
        product = Product.browse(product_id).exists()
        if not product:
            _logger.warning("lealtad: falta el producto %s", product_id)
            continue
        existing = program.with_context(active_test=False).reward_ids.filtered(
            lambda r: r.reward_type == 'product' and r.reward_product_id == product)
        vals = {'required_points': points, 'description': description, 'active': True}
        if existing:
            existing[:1].write(vals)
        else:
            env['loyalty.reward'].create(dict(vals, program_id=program.id, reward_type='product',
                                              reward_product_id=product.id, reward_product_qty=1))
    five = env['loyalty.program'].search([('name', '=', NEXT_ORDER_5_PCT)])
    five.write({'active': False})
    _logger.info("lealtad: premios Crilimp cargados; '%s' apagado (%s)", NEXT_ORDER_5_PCT, five.ids)
