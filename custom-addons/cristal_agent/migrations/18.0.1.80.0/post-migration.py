# -*- coding: utf-8 -*-
"""Migración 18.0.1.80.0 — Retiro en el local SOLO con pedido previo (Joaco, 20/11/2026).

"Los pedidos para retirar en el local deben hacerse anticipadamente. No pueden ir a retirar
en el local sin orden previa … eso tiene una demora, no se atiende inmediatamente ya que se
pierde demasiado tiempo atendiendo mayoristas. Tenemos que rumbear a que vayan con el
pedido listo."
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

MARK = "RETIRO EN EL LOCAL: SOLO CON PEDIDO PREVIO"
BLOCK = (
    "## ⚠️ " + MARK + " (Joaco, 20/11/2026 — pisa cualquier otra indicación de este texto)\n"
    "- El mayorista que retira en el local (San Martín 2350) tiene que hacer el pedido **antes, "
    "por acá**. En el local **no se arma en el momento**: se prepara y le avisamos por WhatsApp "
    "cuando está listo; recién ahí pasa a retirar.\n"
    "- Si dice \"paso ahora y compro allá\" o \"voy a ver al local\", explicale con buena onda que "
    "para no hacerlo esperar le armamos el pedido antes: que te diga qué necesita (le pasás la "
    "lista) y se lo dejamos preparado. Nunca le digas que pase cuando quiera ni que lo atienden "
    "en el momento.\n"
    "- Al confirmar un retiro: \"Lo preparamos y te avisamos por WhatsApp cuando esté listo para "
    "retirar\" (no prometas hora). Que traiga los bidones vacíos con tapa.\n"
    "- Esto es para mayoristas. El consumidor final que compra para su casa puede pasar por el "
    "local cuando quiera.\n\n")

KB_CONTENT = (
    "RETIRO EN EL LOCAL CON PEDIDO PREVIO (Joaco, 20/11/2026): los mayoristas retiran SOLO con "
    "pedido hecho antes por WhatsApp. El pedido no se arma en el momento (atender mayoristas en "
    "el mostrador hace perder ventas de consumidor final): se prepara y se le avisa por WhatsApp "
    "cuando está listo para retirar. Si quiere pasar sin pedido, ofrecerle armarlo por acá. En el "
    "local hay una lista impresa de bidones de 20 L y se le puede mandar la lista completa por "
    "WhatsApp para que la arme tranquilo.")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if config and config.system_prompt and MARK not in config.system_prompt:
        config.system_prompt = BLOCK + config.system_prompt
    KB = env['cristal.agent.knowledge'].with_context(active_test=False)
    if not KB.search_count([('name', 'ilike', 'Retiro en el local con pedido previo')]):
        KB.create({'name': 'Retiro en el local con pedido previo (mayoristas)',
                   'category': 'regla_negocio', 'applies_to': 'all',
                   'client_type_filter': 'mayorista', 'source': 'chat_joaco', 'priority': 340,
                   'content': KB_CONTENT})
    _logger.info("✅ MIGRATION 1.80.0: retiro solo con pedido previo")
