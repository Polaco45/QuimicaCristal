# -*- coding: utf-8 -*-
"""1.82.2 — Pedido confirmado que el cliente pasa a retirar (Joaco 26/11/2026, caso Leila
S07183): Claudio usa switch_order_to_pickup y le dice el total nuevo en el momento."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

MARK = "PEDIDO CONFIRMADO QUE PASA A RETIRO"
BLOCK = (
    "## ⚠️ " + MARK + " (Joaco, 26/11/2026)\n"
    "Si un cliente con pedido CONFIRMADO para el camión o con envío dice que mejor lo pasa "
    "a retirar por la planta: switch_order_to_pickup(order_id) (y remove_product_names si "
    "dijo que algo ya no lo quiere). Saca el flete, lo pasa a retiro y le avisa al depósito. "
    "En el MISMO mensaje decile el total nuevo y cómo pagar (alias crilimp). Nunca le digas "
    "'te confirmo el monto después'.\n\n")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if config and config.system_prompt and MARK not in config.system_prompt:
        config.system_prompt = BLOCK + config.system_prompt
    _logger.info("1.82.2: switch_order_to_pickup en el prompt")
