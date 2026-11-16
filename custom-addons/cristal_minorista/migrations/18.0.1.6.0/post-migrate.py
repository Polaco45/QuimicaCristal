# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # 16/11/2026: la caja guardaba el prefijo "+54" como celular cuando no se cargaba número
    # (1.024 contactos). No es un teléfono: se borra. La clave de WhatsApp no cambia (ya
    # salía vacía con "+54"; si el contacto tiene teléfono, la clave sale de ahí).
    for field in ('mobile', 'phone'):
        cr.execute(f"""
            UPDATE res_partner SET {field} = NULL
             WHERE {field} IS NOT NULL
               AND regexp_replace({field}, '[^0-9]', '', 'g') IN ('', '54', '549', '5490')
        """)
        _logger.info("cristal_minorista 1.6.0: %s contactos sin '+54' suelto en %s", cr.rowcount, field)
