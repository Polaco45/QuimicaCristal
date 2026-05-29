# -*- coding: utf-8 -*-
"""
Extensión de product.template para marcar productos del Catálogo Mayorista.

Joaco usa una vista propia "Catálogo Mayorista" donde marca/desmarca productos.
El bot usa este flag para:
1. Generar el PDF de Lista Mayorista (incluye solo productos con is_mayorista_catalog=True)
2. Sugerir productos al armar cotizaciones
"""
from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_mayorista_catalog = fields.Boolean(
        string="En Catálogo Mayorista",
        default=False,
        help="Marcalo si este producto va en la Lista de Precios Mayorista "
             "y/o lo querés que el bot Claudio lo sugiera al armar cotizaciones.",
        index=True,
    )

    mayorista_priority = fields.Integer(
        string="Prioridad Mayorista",
        default=50,
        help="Mayor número = aparece primero en la lista. Default 50.",
    )
