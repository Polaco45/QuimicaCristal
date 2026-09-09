# -*- coding: utf-8 -*-
"""Separación Vendedor ↔ Visitador.

Hasta v4.4.0 el plan usaba `user_id` (el Vendedor comercial, que define a nombre
de quién salen las cotizaciones) también para decir quién visitaba al cliente.
Eso obligaba a poner a la vendedora como Vendedor de clientes que no son suyos.

Desde v4.5.0 existe `visit_user_id` ("Quién lo visita"). Acá se copia el valor
actual para que nadie desaparezca de "Mi día" tras la actualización.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE res_partner
           SET visit_user_id = user_id
         WHERE visit_plan_active IS TRUE
           AND visit_user_id IS NULL
           AND user_id IS NOT NULL
    """)
