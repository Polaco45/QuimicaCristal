# -*- coding: utf-8 -*-
"""Migración 18.0.1.79.0 — Bidones de 20 L (20/11/2026).

"Desde hoy no se vende más producto a granel: el granel es solo lo que está en el tanque.
Lo ya vendido se entrega como está. De ahora en más se venden los productos 'x 20 lts', que
ya tienen stock propio y precio. Hay que cambiar el agente de venta mayorista para que
ofrezca bidones de 20; el precio por litro sale de dividir el precio del bidón por 20."

- Catálogo mayorista: entran los "x 20 lts" a la venta y salen los "a granel" (lista de
  precios, buscador y placas usan esa marca).
- Oferta "Combo Revendedor" y reglas de la base de conocimiento que hablaban de granel.
- Aviso al principio del prompt de Claudio.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

MARK = "LÍQUIDOS: SOLO BIDONES DE 20 L"
BLOCK = (
    "## ⚠️ " + MARK + " (20/11/2026 — pisa cualquier otra indicación de este texto)\n"
    "Desde el 20/11/2026 **ya NO se vende a granel** (por litro suelto). Los líquidos se venden "
    "**por bidón cerrado de 20 L**: los productos \"x 20 lts\" (ej. \"Jabon B/E Ariel x 20 lts\", "
    "\"Limpiador Desod. x 20 lts (Lavanda)\").\n"
    "- `search_products` devuelve `price` = precio del **bidón** y `precio_por_litro` = bidón ÷ 20. "
    "Cotizá y cobrá por bidón; el precio por litro lo podés decir para comparar (\"sale $X el "
    "bidón de 20 L, $Y el litro\").\n"
    "- En `create_sale_order` la `qty` es **cantidad de bidones** (60 L = 3 bidones). Nunca "
    "medio bidón.\n"
    "- Donde este texto, la base de conocimiento o una oferta digan \"a granel\", \"mínimo 20 L\" o "
    "\"precio por litro\", leé \"bidón de 20 L\" y precio por bidón. El recambio de bidones sigue "
    "igual (vacío con tapa por cada bidón, o bidón nuevo con cargo).\n"
    "- Lo que un cliente ya compró a granel se entrega como está: no lo cambies.\n\n")

NEW_KB = (
    "BIDONES DE 20 L (20/11/2026): ya NO se vende a granel ni por litro suelto. Los líquidos "
    "(jabones, suavizantes, detergentes, lavandinas, cloro, desengrasantes, limpiadores, ceras, "
    "jabón de manos, quitamanchas, químicos de pileta) se venden por BIDÓN cerrado de 20 L: "
    "los productos 'x 20 lts'. El precio de la lista es por bidón; el precio por litro es el del "
    "bidón dividido 20. Se cotiza por cantidad de bidones (no hay medio bidón). El recambio de "
    "bidones vacíos con tapa sigue igual. Lo vendido a granel antes del 20/11 se entrega como está.")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Tmpl = env['product.template'].with_context(active_test=False)
    x20 = Tmpl.search([('name', '=ilike', '% x 20 lts%'), ('sale_ok', '=', True)])
    x20.write({'is_mayorista_catalog': True})
    granel = Tmpl.search([('is_mayorista_catalog', '=', True), ('name', 'ilike', 'granel'),
                          ('sale_ok', '=', False)])
    granel.write({'is_mayorista_catalog': False})

    from odoo.addons.cristal_agent.services.tools.search_products import bidon20_equivalent

    offer = env['cristal.agent.offer'].search([('name', 'ilike', 'Combo Revendedor')], limit=1)
    if offer:
        prods = env['product.product']
        for p in offer.product_ids:
            prods |= bidon20_equivalent(env, p) or p
        offer.write({
            'product_ids': [(6, 0, prods.ids)],
            'name': 'Combo Revendedor puerta a puerta (bidones de 20 L)',
            'description': (
                "Combo para quien fracciona y revende, en bidones de 20 L (con recambio de "
                "bidones): " + " + ".join(prods.mapped('display_name')) + ". Precio: Lista "
                "Mayorista del día, por bidón. Se ofrece a calificados sin cotizar que revenden "
                "fraccionado en la acción del día 10."),
        })

    KB = env['cristal.agent.knowledge'].with_context(active_test=False)
    old = KB.search([('active', '=', True), '|', '|', '|',
                     ('name', 'ilike', 'Mínimo 20L aplica'),
                     ('name', 'ilike', 'Formatos de venta productos a granel'),
                     ('name', 'ilike', 'granel: múltiplos de 20'),
                     ('name', 'ilike', 'Mínimo 20L aplica SOLO a granel')])
    old.write({'active': False})
    if not KB.search_count([('name', 'ilike', 'BIDONES DE 20 L: ya no se vende a granel')]):
        KB.create({'name': 'BIDONES DE 20 L: ya no se vende a granel (20/11/2026)',
                   'category': 'regla_negocio', 'applies_to': 'all',
                   'client_type_filter': 'both', 'source': 'chat_joaco', 'priority': 350,
                   'content': NEW_KB})
    pisos = KB.search([('name', 'ilike', 'Desodorante / perfumina de pisos')], limit=1)
    note = ("ACTUALIZADO 20/11/2026: ya no hay granel. El producto es 'Limpiador Desod. x 20 lts "
            "(<aroma>)', bidón de 20 L, se vende por bidón.\n\n")
    if pisos and not (pisos.content or '').startswith('ACTUALIZADO 20/11/2026'):
        pisos.content = note + (pisos.content or '')

    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if config and config.system_prompt and MARK not in config.system_prompt:
        config.system_prompt = BLOCK + config.system_prompt
    _logger.info("✅ MIGRATION 1.79.0: bidones de 20 L — %s al catálogo, %s granel fuera, "
                 "%s reglas viejas apagadas", len(x20), len(granel), len(old))
