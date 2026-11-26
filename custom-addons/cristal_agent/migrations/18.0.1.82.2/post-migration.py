# -*- coding: utf-8 -*-
"""1.82.2 — El código del evento de CIMA Oulton es OULTON15, no OUTLON15 (Joaco, 26/11/2026).

- El evento pasa a código OULTON15 (el que da Claudio y el que se canjea: la regla 101 del
  programa 92 ya se cambió a OULTON15). OUTLON15 queda como variante reconocida por si llega
  escrito así (QR o volante viejo).
- Etiquetas, lista de correo y regla de conocimiento 132 con el código nuevo.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

OLD, NEW = 'OUTLON15', 'OULTON15'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Event = env['cristal.agent.event'].sudo().with_context(active_test=False)
    ev = Event.search([('code', 'in', (OLD, NEW))], limit=1)
    if ev:
        ev.write({'code': NEW, 'code_aliases': OLD, 'name': 'RMI / CIMA Oulton (premios)',
                  'keywords': 'rmi, cima, oulton, outlon'})
        for rec in (ev.partner_tag_id, ev.crm_tag_id, ev.mailing_list_id):
            if rec and OLD in (rec.name or ''):
                rec.write({'name': rec.name.replace(OLD, NEW)})
        env['cristal.agent.event.contact'].sudo().search(
            [('event_id', '=', ev.id)]).rename_leads()
        _logger.info("1.82.2: evento %s → %s (variante %s).", OLD, NEW, OLD)

    KB = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    kb = KB.browse(132).exists()
    if not kb or 'HISPANO15' not in (kb.name or ''):
        kb = KB.search([('name', 'ilike', 'HISPANO15')], limit=1)
    if kb:
        content = (kb.content or '').replace(
            "(también puede escribir OULTON15: es el mismo cupón, el código que se canjea es "
            "OUTLON15)",
            "(si escribe OUTLON15 es el mismo cupón: el código que se canjea es OULTON15)")
        content = content.replace(OLD, NEW).replace(
            "si escribe OULTON15 es el mismo cupón", "si escribe OUTLON15 es el mismo cupón")
        kb.write({'name': (kb.name or '').replace(OLD, NEW), 'content': content})
        _logger.info("1.82.2: KB %s con el código %s.", kb.id, NEW)
