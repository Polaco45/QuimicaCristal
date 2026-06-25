# -*- coding: utf-8 -*-
"""
Migración 18.0.1.15.0 — El bot deja de trabajar como "Claudio" y pasa a OdooBot.

Joaco da de baja el usuario Claudio (res.users 721 / res.partner 80799) para no
pagar una licencia al pedo. De ahora en más el bot opera como **OdooBot**
(res.users 1 / res.partner 2), que es el usuario de sistema (gratis).

Esta migración:
1. Fija en la config bot_user_id=OdooBot (1) y bot_partner_id=OdooBot (2).
2. Reasigna TODO lo que estaba a nombre de Claudio (721) → OdooBot (1):
   oportunidades (crm.lead, incluidas archivadas), actividades (mail.activity) y
   órdenes de venta (sale.order). Así Joaco puede archivar/eliminar el usuario
   Claudio sin dejar registros colgados.

La autoría histórica de los mensajes (mail.message.author_id = 80799) se deja como
está: es historial y no afecta la operación; el partner queda archivado.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

OLD_USER = 721      # Claudio (res.users)
NEW_USER = 1        # OdooBot (res.users de sistema)
NEW_PARTNER = 2     # OdooBot (res.partner)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1) Config → OdooBot (idempotente)
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if config:
        config.write({'bot_user_id': NEW_USER, 'bot_partner_id': NEW_PARTNER})
        _logger.info("✅ MIGRATION 1.15.0: config bot_user/partner → OdooBot (1/2)")

    # 2) Reasignar lo que estaba como Claudio → OdooBot
    # crm.lead (incluye archivadas con active_test=False)
    leads = env['crm.lead'].with_context(active_test=False).search(
        [('user_id', '=', OLD_USER)])
    if leads:
        leads.write({'user_id': NEW_USER})
        _logger.info("✅ MIGRATION 1.15.0: %s oportunidades reasignadas 721→1", len(leads))

    # mail.activity (recordatorios pendientes del bot)
    acts = env['mail.activity'].search([('user_id', '=', OLD_USER)])
    if acts:
        acts.write({'user_id': NEW_USER})
        _logger.info("✅ MIGRATION 1.15.0: %s actividades reasignadas 721→1", len(acts))

    # sale.order (vendedor)
    orders = env['sale.order'].with_context(active_test=False).search(
        [('user_id', '=', OLD_USER)])
    if orders:
        orders.write({'user_id': NEW_USER})
        _logger.info("✅ MIGRATION 1.15.0: %s órdenes de venta reasignadas 721→1", len(orders))

    _logger.info("✅ MIGRATION 1.15.0: el bot ahora opera como OdooBot. "
                 "Ya se puede dar de baja el usuario Claudio (721).")
