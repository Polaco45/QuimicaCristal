# -*- coding: utf-8 -*-
import logging

from . import models

_logger = logging.getLogger(__name__)

# Productos (product.product) de Química Cristal usados en los combos.
JABON_PREMIUM_5L = [5433]
SUAVIZANTE_5L = [5582, 5585]
LAVANDINA_5L = [11960]
LIMP_DESOD_5L = [5494, 5495, 5497, 5501, 5496, 5498, 5499]
DESENGRASANTE_5L = [5316]
DETERGENTE_5L = [6335]
BOLSA_80X110 = [11652]
BOLSA_50X70 = [11748]
REJILLA = [4889]
PANO_ABSORBENTE = [4755]
GUANTES = [5415, 5417]
TRAPO_PISO = [5062]
ESPONJA_ACERO = [4399]
PANO_VAJILLA = [4764]
PERFUME_ROPA_1L = [5527, 5531, 5523, 5519, 5535]
CLORO_GRANULADO_1KG = [6278]
PASTILLA_GRANDE_1KG = [6286]
ALGUICIDA_1L = [5205]
CLARIFICADOR_1L = [5291]
BOYA = [4058]

COMBOS = [
    ('Combo Casa Completa', 39900, [
        ('Jabón Premium 5L', JABON_PREMIUM_5L), ('Suavizante 5L', SUAVIZANTE_5L),
        ('Lavandina 5L', LAVANDINA_5L), ('Limpiador desodorante 5L', LIMP_DESOD_5L),
        ('Desengrasante 5L', DESENGRASANTE_5L), ('Detergente 5L', DETERGENTE_5L),
        ('Bolsa 80x110', BOLSA_80X110), ('Rejilla', REJILLA), ('Paño absorbente', PANO_ABSORBENTE),
        ('Guantes', GUANTES)]),
    ('Combo Limpieza Total', 29900, [
        ('Lavandina 5L', LAVANDINA_5L), ('Limpiador desodorante 5L', LIMP_DESOD_5L),
        ('Desengrasante 5L', DESENGRASANTE_5L), ('Detergente 5L', DETERGENTE_5L),
        ('Bolsa 80x110', BOLSA_80X110), ('Bolsa 50x70', BOLSA_50X70), ('Rejilla', REJILLA),
        ('Trapo de piso', TRAPO_PISO), ('Guantes', GUANTES), ('Esponja de acero', ESPONJA_ACERO)]),
    ('Combo Pileta', 32900, [
        ('Cloro granulado 1kg', CLORO_GRANULADO_1KG), ('Cloro granulado 1kg (2°)', CLORO_GRANULADO_1KG),
        ('Pastilla grande 1kg', PASTILLA_GRANDE_1KG), ('Alguicida 1L', ALGUICIDA_1L),
        ('Clarificador 1L', CLARIFICADOR_1L), ('Boya', BOYA)]),
    ('Combo Lavadero Completo', 18900, [
        ('Jabón Premium 5L', JABON_PREMIUM_5L), ('Suavizante 5L', SUAVIZANTE_5L),
        ('Perfume para ropa 1L', PERFUME_ROPA_1L), ('Lavandina 5L', LAVANDINA_5L)]),
    ('Combo Cocina', 15400, [
        ('Detergente 5L', DETERGENTE_5L), ('Desengrasante 5L', DESENGRASANTE_5L), ('Rejilla', REJILLA),
        ('Esponja de acero', ESPONJA_ACERO), ('Paño fibra vajilla', PANO_VAJILLA)]),
    ('Combo Casa Limpia', 9900, [
        ('Lavandina 5L', LAVANDINA_5L), ('Limpiador desodorante 5L', LIMP_DESOD_5L),
        ('Trapo de piso', TRAPO_PISO), ('Paño absorbente', PANO_ABSORBENTE)]),
]

# Promo de caja: el cliente elige 2 de estos (combinables) por un precio fijo.
PINO_AROMATIZANTE = [5538, 5539, 5540, 5541, 5542, 5543]
PALILLERO = [4737]
LIMP_DESOD_900CC = [11765, 11766, 11767, 11768]
GATILLO = [4470]
CHECKOUT_ITEMS = PINO_AROMATIZANTE + PALILLERO + ESPONJA_ACERO + LIMP_DESOD_900CC + GATILLO
CHECKOUT_ITEMS_TEXT = 'pino aromatizante, palillero, esponja de acero, limpiador 900cc o gatillo'
CHECKOUT_PROMO = ('Promo caja: 2 por $1.999', 1999, [('Elegí uno', CHECKOUT_ITEMS), ('Elegí otro', CHECKOUT_ITEMS)])

CF_PRICELIST_ID = 19          # L.C 1
CF_FISCAL_POSITION_NAME = 'Ventas X'


def _combos_category(env):
    category = env['pos.category'].search([('name', '=', 'Combos')], limit=1)
    if not category:
        category = env['pos.category'].create({'name': 'Combos', 'sequence': -100})
    return category


def _create_combo(env, name, price, slots, category):
    """Crea el producto combo si no existe. Devuelve el product.product."""
    template = env['product.template'].with_context(active_test=False).search(
        [('name', '=', name), ('type', '=', 'combo')], limit=1)
    if template:
        return template.product_variant_id
    Product = env['product.product']
    existing = set(Product.browse([pid for _s, ids in slots for pid in ids]).exists().ids)
    # Los productos son de una empresa: el combo tiene que ser de la misma. Por eso
    # su precio no va en L.C 1 (lista sin empresa) sino como precio de venta, en una
    # categoría sin reglas en esa lista.
    company = Product.browse(JABON_PREMIUM_5L).exists().company_id
    combo_categ = env['product.category'].search([('name', '=', 'Combos y Kit')], limit=1)
    combo_ids = []
    for slot_name, ids in slots:
        ids = [pid for pid in ids if pid in existing]
        if not ids:
            _logger.warning("venta guiada: %s / %s sin productos, lo salteo", name, slot_name)
            continue
        combo = env['product.combo'].create({
            'name': f"{name.replace('Combo ', '')} · {slot_name}",
            'company_id': company.id,
            'combo_item_ids': [(0, 0, {'product_id': pid, 'extra_price': 0.0}) for pid in ids],
        })
        combo_ids.append(combo.id)
    template = env['product.template'].create({
        'name': name,
        'company_id': company.id,
        'type': 'combo',
        'list_price': price,
        'categ_id': combo_categ.id or env.ref('product.product_category_all').id,
        'sale_ok': True,
        'available_in_pos': True,
        'pos_categ_ids': [(6, 0, category.ids)],
        'combo_ids': [(6, 0, combo_ids)],
        'taxes_id': [(5, 0, 0)],
    })
    _logger.info("venta guiada: creado %s ($%s, %s opciones)", name, price, len(combo_ids))
    return template.product_variant_id


def setup_checkout_promo(env):
    category = _combos_category(env)
    promo = _create_combo(env, *CHECKOUT_PROMO, category)
    for config in env['pos.config'].search([('cristal_vg_enabled', '=', True)]):
        if not config.cristal_vg_checkout_product_id:
            config.cristal_vg_checkout_product_id = promo
        if not config.cristal_vg_checkout_items_text:
            config.cristal_vg_checkout_items_text = CHECKOUT_ITEMS_TEXT


def setup_venta_guiada(env):
    category = _combos_category(env)
    for name, price, slots in COMBOS:
        _create_combo(env, name, price, slots, category)

    for config in env['pos.config'].search([('pricelist_id', '=', CF_PRICELIST_ID)]):
        vals = {}
        if not config.cristal_vg_fiscal_position_ids:
            fp = env['account.fiscal.position'].search(
                [('name', '=', CF_FISCAL_POSITION_NAME), ('company_id', '=', config.company_id.id)], limit=1)
            vals['cristal_vg_fiscal_position_ids'] = [(6, 0, fp.ids)]
        # Restringir categorías sin ninguna cargada muestra todo: agregar Combos ahí
        # dejaría la caja mostrando solo combos.
        if (config.limit_categories and config.iface_available_categ_ids
                and category not in config.iface_available_categ_ids):
            vals['iface_available_categ_ids'] = [(4, category.id)]
        vals['cristal_vg_enabled'] = True
        # pos.config no deja tocar categorías con sesión abierta salvo con este contexto.
        config.with_context(bypass_categories_forbidden_change=True).write(vals)

    setup_checkout_promo(env)
    env['cristal.vg.suggestion']._cron_recompute()


def post_init_hook(env):
    setup_venta_guiada(env)
