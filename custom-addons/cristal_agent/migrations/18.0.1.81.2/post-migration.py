# -*- coding: utf-8 -*-
"""1.81.2 — Novedades del depósito (Joaco 24/11/2026, caso Tefi S07488): Guillermo avisa
"no hay X, ¿le mandamos Y?", Claudio consulta al cliente, cambia el pedido confirmado con
swap_order_product y esa tool le avisa al depósito."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

MARK = "NOVEDADES DEL DEPÓSITO"
BLOCK = (
    "## ⚠️ " + MARK + " (Joaco, 24/11/2026)\n"
    "Si en el chat le avisamos al cliente que falta un producto de su pedido CONFIRMADO y le "
    "ofrecimos otro (\"no tenemos frutilla, ¿te sirve blanco?\"), cuando conteste:\n"
    "- Acepta → swap_order_product(order_id, producto viejo, producto nuevo) con el mismo "
    "precio, y confirmale en una línea.\n"
    "- No lo quiere → swap_order_product(order_id, producto viejo) SIN producto nuevo: lo saca "
    "del pedido. Decile el total nuevo.\n"
    "La tool le avisa sola al depósito (Guillermo). No escales a Joaco por esto.\n\n")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if config and config.system_prompt and MARK not in config.system_prompt:
        config.system_prompt = BLOCK + config.system_prompt
    _logger.info("1.81.2: bloque de novedades del depósito en el prompt")
