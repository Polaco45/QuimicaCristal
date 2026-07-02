# -*- coding: utf-8 -*-
"""
Migración 18.0.1.27.0 — Combo Emprendedor: base 500cc → 1 lt.

La línea del combo que usaba "Base Limpiador Desodorante (1+80) Arpege, 500cc"
(product 5232) pasa a la variante de 1 litro (product 5233). Decisión de Joaco.
Se hace por código porque el modelo cristal.agent.combo.line no está expuesto al
conector MCP.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

OLD_PRODUCT = 5232  # Base Limpiador Desodorante (1+80) (Arpege, 500cc)
NEW_PRODUCT = 5233  # Base Limpiador Desodorante (1+80) (Arpege, 1 lt)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Line = env['cristal.agent.combo.line']
    Product = env['product.product']

    new_prod = Product.browse(NEW_PRODUCT)
    if not new_prod.exists():
        _logger.warning("MIGRATION 1.27.0: producto destino %s no existe; abort", NEW_PRODUCT)
        return

    lines = Line.search([('product_id', '=', OLD_PRODUCT)])
    if not lines:
        _logger.info("MIGRATION 1.27.0: no hay líneas de combo con el 500cc (nada que cambiar)")
        return
    lines.write({'product_id': NEW_PRODUCT})
    _logger.info("✅ MIGRATION 1.27.0: %s línea(s) de combo cambiadas de 500cc a 1 lt (→ %s)",
                 len(lines), new_prod.display_name)
