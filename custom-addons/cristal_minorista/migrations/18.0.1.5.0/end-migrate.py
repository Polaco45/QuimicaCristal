# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Joaco, 04/11/2026: las promos van a todos los que tienen WhatsApp, salvo los que
    # pidieron la baja; ya no hace falta haber aceptado. El campo guardado se recalcula acá
    # porque cambió de qué depende.
    cr.execute("""
        UPDATE res_partner
           SET cristal_mkt_allowed = (coalesce(cristal_wa_key, '') <> '' AND NOT coalesce(cristal_mkt_optout, false))
    """)
    cr.execute("SELECT count(*) FROM res_partner WHERE cristal_mkt_allowed")
    _logger.info("cristal_minorista 1.5.0: %s contactos habilitados para avisos", cr.fetchone()[0])
