# -*- coding: utf-8 -*-
"""1.82.5 — Cupones de eventos: prueba de conversación real (simulación) y ajustes que salieron
de esa prueba (26/11/2026): Claudio recomendaba un combo de $6.490 sin avisar el mínimo de
$20.000 y ofrecía tomar el pedido por WhatsApp. Ahora: sugerencia que llegue a $20.000, web o
local, y si insiste en WhatsApp escala a Joaco (create_sale_order/quote_entry_combo frenan).
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

OLD_HELP = "Ayudalo a elegir para que use el cupón."
NEW_HELP = ("Ayudalo a elegir una compra que llegue a $20.000 (mínimo del cupón) para que use "
            "el 15%: si lo que pide es menos, sugerile qué sumar.")
OLD_ESC = "Si quiere hacer el pedido por WhatsApp con envío"
NEW_ESC = ("NO le cotices ni le armes el pedido vos (no uses create_sale_order con estos "
           "clientes). Si quiere hacer el pedido por WhatsApp con envío")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    KB = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    kb = KB.browse(132).exists()
    if not kb or 'HISPANO15' not in (kb.name or ''):
        kb = KB.search([('name', 'ilike', 'HISPANO15')], limit=1)
    if not kb:
        return
    content = kb.content or ''
    if NEW_HELP not in content:
        content = content.replace(OLD_HELP, NEW_HELP)
    if NEW_ESC not in content:
        content = content.replace(OLD_ESC, NEW_ESC)
    kb.write({'content': content})
    _logger.info("1.82.5: KB %s con mínimo de $20.000 y sin pedidos por WhatsApp.", kb.id)
