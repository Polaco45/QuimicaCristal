# -*- coding: utf-8 -*-
"""Recalcula visit_frequency_days con la lógica de semanas.

Es un campo almacenado: al cambiar su cálculo (14 días en quincenal, no 15) los
registros viejos quedaron con el valor anterior. Ahora siempre son semanas × 7.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE res_partner
           SET visit_frequency_days = CASE visit_frequency
                   WHEN 'semanal' THEN 7
                   WHEN 'mensual' THEN 28
                   ELSE 14
               END
         WHERE visit_frequency IS NOT NULL
    """)
