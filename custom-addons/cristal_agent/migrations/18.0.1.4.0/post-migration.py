# -*- coding: utf-8 -*-
"""
Migración a v18.0.1.4.0:
- Limpia leads duplicados generados por bug en versiones anteriores.
- Para cada partner con >1 lead agent_managed activo, deja solo el más reciente.
- Los otros los marca como lost con motivo "Duplicado limpiado en migración 1.4.0".
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    Lead = env['crm.lead'].sudo()

    # Buscar partners con más de 1 lead activo gestionado por el agente
    cr.execute("""
        SELECT partner_id, COUNT(*) AS n
        FROM crm_lead
        WHERE agent_managed = TRUE
          AND active = TRUE
          AND partner_id IS NOT NULL
        GROUP BY partner_id
        HAVING COUNT(*) > 1
    """)
    rows = cr.fetchall()

    if not rows:
        _logger.info("MIGRATION 1.4.0: no se encontraron leads duplicados")
        return

    total_archived = 0
    for partner_id, count in rows:
        # Obtener todos los leads del partner ordenados por fecha desc
        leads = Lead.search([
            ('partner_id', '=', partner_id),
            ('agent_managed', '=', True),
            ('active', '=', True),
        ], order='create_date desc')

        if len(leads) <= 1:
            continue

        # Dejar el más reciente, archivar los otros
        keep = leads[0]
        to_archive = leads[1:]

        try:
            to_archive.write({
                'active': False,
                'description': (keep.description or '') + (
                    f"\n[Migration 1.4.0] Duplicado limpiado, lead activo conservado: {keep.id}"
                ),
            })
            total_archived += len(to_archive)
            _logger.info(
                "MIGRATION 1.4.0: partner %s tenía %s leads — dejé %s activo, archivé %s",
                partner_id, count, keep.id, [l.id for l in to_archive]
            )
        except Exception as e:
            _logger.exception(
                "MIGRATION 1.4.0: error limpiando duplicados de partner %s: %s",
                partner_id, e
            )

    _logger.info(
        "✅ MIGRATION 1.4.0: limpieza completada. %s leads duplicados archivados.",
        total_archived
    )
