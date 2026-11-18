# -*- coding: utf-8 -*-
"""Migración 18.0.1.76.0 — Joaco (18/11/2026): "no quiero intervenir más yo en pedidos, que
sea autónomo". Claudio confirma todos los pedidos cuando el cliente da el OK:

- Sin tope de monto para la confirmación automática.
- No se le pide más a Joaco por WhatsApp que confirme (cristal_agent.owner_confirm_whatsapp = 0).
- Aviso al principio del prompt: los pedidos los confirma Claudio; lo que falte se resuelve
  con el cliente.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

MARK = "PEDIDOS: LOS CONFIRMÁS VOS, SIEMPRE"
BLOCK = (
    "## ⚠️ " + MARK + " (Joaco, 18/11/2026 — pisa cualquier otra indicación de este texto)\n"
    "Joaquín **ya no confirma pedidos**. **Nunca** digas \"queda pendiente de confirmación de "
    "Joaquín\" ni escales con \"PEDIDO PARA CONFIRMAR\", sea cual sea el monto.\n"
    "- Cuando el cliente da el OK: juntá lo que falte (dirección exacta o que retira, bidones, "
    "efectivo o transferencia) y llamá `confirm_order` (o `confirm_cf_order`). Si devuelve "
    "`ok`, está confirmado: decíselo con el detalle de pago.\n"
    "- Si devuelve `not_confirmed`, lo resolvés **con el cliente** siguiendo `message_for_bot`: "
    "sin stock → confirmar con lo que hay o esperar la reposición; localidad sin reparto o con "
    "el camión pausado → retiro en el local o comisionista (`delivery_mode='retiro'`); saldo "
    "vencido → primero se regulariza (pasale el saldo); salida del camión ya pasada → próxima "
    "salida o retiro.\n"
    "- Mientras falte un dato, decile al cliente **qué falta** y que con eso queda confirmado. "
    "Si el cliente contesta a un recordatorio de cotización con un \"sí\", \"dale\" u \"ok\", "
    "tomalo como aceptación: pedí solo lo que falte y confirmá.\n"
    "- A Joaco se escala solo por reclamos o por algo fuera de lo normal que pide el cliente "
    "(descuento especial, cuenta corriente, plazo de pago).\n\n")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ir.config_parameter'].set_param('cristal_agent.owner_confirm_whatsapp', '0')
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        return
    if config.auto_confirm_max_amount:
        config.auto_confirm_max_amount = 0.0
    text = config.system_prompt or ''
    if text and MARK not in text:
        config.system_prompt = BLOCK + text
    _logger.info("✅ MIGRATION 1.76.0: Claudio confirma solo (sin tope, sin pedido a Joaco).")
