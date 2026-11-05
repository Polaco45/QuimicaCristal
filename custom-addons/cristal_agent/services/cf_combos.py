# -*- coding: utf-8 -*-
"""Combos para la casa (consumidor final) — v1.60.

Joaco (05/11/2026): "no es coherente a la hora de ofrecer los combos minoristas, no
sabe ni qué tienen". Claudio sabía nombre y precio (texto fijo del prompt) pero no qué
traía cada combo; a Angy le dijo "trae productos para toda la casa" y lo escaló a Joaco.
Y si cotizaba un combo, salía en $0 y sin productos (S06923).

Este módulo arma, desde los combos reales de Odoo (los mismos de la caja):
- el catálogo para el prompt: qué trae cada combo, qué aromas/colores se pueden elegir,
  precio, cuánto sale suelto y cuánto ahorra, y si hoy falta stock de algo;
- la elección de productos para cotizar un combo (create_sale_order lo arma con sus
  líneas de combo, como lo hace la web y la caja).
"""
import logging
import re
import unicodedata

_logger = logging.getLogger(__name__)

EXCLUDED_NAME = re.compile(r'promo caja', re.I)


def _norm(text):
    text = unicodedata.normalize('NFKD', (text or '').lower())
    return ''.join(c for c in text if not unicodedata.combining(c))


def _clean(name):
    return re.sub(r'^\[[^\]]*\]\s*', '', name or '').strip()


def _money(v):
    return '$' + f'{int(round(v or 0)):,}'.replace(',', '.')


def _available(product):
    """Stock que se puede vender. None = no se controla (fabricación / no almacenable)."""
    if not getattr(product, 'is_storable', False):
        return None
    try:
        return product.qty_available or 0.0
    except Exception:  # noqa: BLE001
        return None


def _in_stock(product, qty=1.0):
    avail = _available(product)
    return avail is None or avail >= qty


def _variant_label(product):
    """Lo que distingue a la variante: "(Limon, 5 lts)" → "Limon, 5 lts"."""
    m = re.search(r'\(([^)]*)\)\s*$', _clean(product.display_name))
    return m.group(1).strip() if m else ''


def combo_products(env):
    """Combos que se le venden al consumidor final (los de la caja, sin la promo de caja)."""
    Product = env['product.product'].sudo()
    combos = Product.search([('type', '=', 'combo'), ('sale_ok', '=', True),
                             ('available_in_pos', '=', True)], order='list_price desc')
    return combos.filtered(lambda p: not EXCLUDED_NAME.search(p.name or '') and p.combo_ids)


def _cf_pricelist(env):
    return env['product.pricelist'].sudo().search([('name', 'ilike', 'L.C 1')], limit=1)


def catalog(env):
    """[{product, name, price, loose, saving, slots: [{name, options: [product], in_stock:
    [product], missing}], missing: [slot names sin stock]}]"""
    pricelist = _cf_pricelist(env)
    result = []
    for combo in combo_products(env):
        slots, loose, missing = [], 0.0, []
        for pc in combo.combo_ids:
            items = pc.combo_item_ids.filtered(lambda i: i.product_id.active and i.product_id.sale_ok)
            options = items.mapped('product_id')
            if not options:
                continue
            prices = []
            for p in options:
                try:
                    prices.append(pricelist._get_product_price(p, 1.0) if pricelist else p.lst_price)
                except Exception:  # noqa: BLE001
                    prices.append(p.lst_price)
            loose += min(prices) if prices else 0.0
            in_stock = options.filtered(_in_stock)
            slot_name = (pc.name or '').split('·')[-1].strip() or _clean(options[0].display_name)
            if not in_stock:
                missing.append(slot_name)
            slots.append({'name': slot_name, 'combo': pc, 'items': items, 'options': options,
                          'in_stock': in_stock})
        price = combo.lst_price
        result.append({
            'product': combo, 'name': _clean(combo.display_name), 'price': price,
            'loose': loose, 'saving': max(loose - price, 0.0), 'slots': slots, 'missing': missing,
        })
    return result


def _slot_text(slot):
    """"Limpiador desodorante 5 lts (Limón, Marina, Cherry)" o el producto si hay uno solo."""
    in_stock = slot['in_stock']
    shown = in_stock or slot['options']
    if len(shown) == 1:
        return _clean(shown[0].display_name)
    labels = [_variant_label(p) for p in shown]
    # Lo que varía es lo primero del paréntesis (aroma/color); el tamaño es el mismo.
    choices = []
    for lab in labels:
        first = lab.split(',')[0].strip() if lab else ''
        if first and first not in choices:
            choices.append(first)
    base = re.sub(r'\s*\([^)]*\)\s*$', '', _clean(shown[0].display_name))
    if choices and len(choices) > 1:
        return f"{base} (a elegir: {', '.join(choices)})"
    return f"{slot['name']} ({' / '.join(_clean(p.display_name) for p in shown[:4])})"


def prompt_block(env):
    """Bloque estable del prompt con el catálogo real de combos para la casa."""
    try:
        data = catalog(env)
    except Exception as e:  # noqa: BLE001
        _logger.warning("combos CF: no pude armar el catálogo: %s", e)
        return ""
    if not data:
        return ""
    lines = ["\n## 🧺 COMBOS PARA LA CASA (consumidor final) — datos de hoy, precio público",
             "Esto es lo que trae cada combo. Usalo TAL CUAL: nunca digas que no sabés qué trae "
             "ni lo consultes con Joaco. Para cotizarlo: create_sale_order(consumidor_final=true) "
             "con la línea {product_id del combo, qty} y, si eligió aromas/colores, "
             "choices=\"Limón, Celeste\" en esa línea (si no elige, va el que hay en stock)."]
    for c in data:
        head = (f"- **{c['name']}** {_money(c['price'])} · suelto {_money(c['loose'])} · "
                f"ahorra {_money(c['saving'])} · product_id={c['product'].id}")
        if c['missing']:
            head += f" · ⛔ HOY NO OFRECER (sin stock: {', '.join(c['missing'])})"
        lines.append(head)
        lines.append("  Trae: " + "; ".join(_slot_text(s) for s in c['slots']) + ".")
    return "\n".join(lines)


def pick_items(combo_product, qty=1.0, choices=None):
    """Elige un combo item por cada parte del combo. Con `choices` ("Limón, Celeste")
    gana la opción en stock cuyo nombre tiene esa palabra; si no, la que más stock tiene.
    Devuelve (items, faltantes, elegidos_por_cliente)."""
    words = [w for w in (_norm(x).strip() for x in re.split(r'[,;/]| y ', choices or '')) if w]
    items, missing, chosen = [], [], []
    for pc in combo_product.combo_ids:
        cands = pc.combo_item_ids.filtered(lambda i: i.product_id.active and i.product_id.sale_ok)
        if not cands:
            continue
        ok = cands.filtered(lambda i: _in_stock(i.product_id, qty))
        pool = ok or cands
        pick = None
        if words:
            for item in pool:
                name = _norm(item.product_id.display_name)
                if any(w in name for w in words):
                    pick = item
                    chosen.append(_clean(item.product_id.display_name))
                    break
        if not pick:
            pick = max(pool, key=lambda i: (_available(i.product_id) is None,
                                            _available(i.product_id) or 0.0))
        if not ok:
            missing.append(_clean(pick.product_id.display_name))
        items.append(pick)
    return items, missing, chosen
