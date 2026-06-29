# -*- coding: utf-8 -*-
"""
Migración 18.0.1.20.0 — Asignar usuarios permitidos a las plantillas de WhatsApp.

Joaco quiere restringir quién usa/ve las plantillas según la cuenta:
- Crilimp (8)  → solo Joaquín (18)
- Ventas (9)   → Joaquín (18) + Alejandra (725)
- Compras (5)  → Guillermo (15) + Sergio (2) + Joaquín (18)

Se setea `whatsapp.template.allowed_user_ids` (campo "Usuarios") por cuenta. La
cuenta Info (3) no se toca. Las plantillas nuevas que se creen después no quedan
asignadas automáticamente (se asignan a mano o se vuelve a correr este criterio).
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

# cuenta wa_account_id -> usuarios permitidos
MAPPING = {
    8: [18],          # Crilimp     → Joaquín
    9: [18, 725],     # Ventas      → Joaquín + Alejandra
    5: [15, 2, 18],   # Compras     → Guillermo + Sergio + Joaquín
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Tmpl = env['whatsapp.template']

    for account_id, user_ids in MAPPING.items():
        tmpls = Tmpl.search([('wa_account_id', '=', account_id)])
        if not tmpls:
            continue
        tmpls.write({'allowed_user_ids': [(6, 0, user_ids)]})
        _logger.info(
            "✅ MIGRATION 1.20.0: %s plantillas de la cuenta %s → usuarios %s",
            len(tmpls), account_id, user_ids)
