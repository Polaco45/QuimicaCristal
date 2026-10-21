# -*- coding: utf-8 -*-
"""Migración 18.0.1.40.0 — Envío de los lunes: solo la oferta marcada, con su texto.

Joaco (19/10/2026) esperaba que el envío de los lunes mandara una promo general a los
mayoristas sin la zona Sur-Oeste. Prendido como estaba, el cron #94 habría mandado la
promo de mayor prioridad (la de cierre de Sur-Oeste) con la descripción interna de
Claudio como texto. Ahora sale solo la oferta marcada "Va en el envío de los lunes".

Oferta #22 (pack de regalo, hasta el 25/10): se marca, con su texto y sin Sur-Oeste.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

PACK_TEXT = ("llevando $150.000 en líquidos (jabón, suavizante, lavandina, cloro, detergente o "
             "desengrasante) te regalamos un pack de 10 artículos: 4 trapos de piso, 4 pares "
             "de guantes y 2 microfibras. Válido hasta el domingo 25/10 o hasta agotar stock")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    offer = env['cristal.agent.offer'].sudo().with_context(active_test=False).browse(22)
    if offer.exists() and 'Pack de regalo' in (offer.name or ''):
        sur_oeste = env['cristal.agent.circuit'].sudo().search(
            [('name', '=', 'Sur-Oeste')], limit=1)
        offer.write({'weekly_broadcast': True, 'broadcast_text': PACK_TEXT,
                     'excluded_circuit_ids': [(6, 0, sur_oeste.ids)]})
        _logger.info("✅ MIGRATION 1.40.0: oferta #22 marcada para el envío de los lunes")
