# -*- coding: utf-8 -*-
"""Tool: search_products — busca productos en el catálogo.

v1.53 (03/11/2026, caso Florencia S06925 y "bases desod de pisos"):
- Cada resultado trae el NOMBRE COMPLETO con sus variantes (aroma, tamaño) y el código:
  antes 14 "Base Limpiador Desodorante (1+80)" iguales y Claudio no sabía cuál era cuál.
- Lo que fabricamos (granel, bases, fraccionado) es A PEDIDO: se cotiza SIEMPRE aunque el
  stock diga 0 (antes Claudio decía "sin stock de Vivere Celeste" y frenaba el pedido).
- Palabras pegadas ("quitasarro", "limpiavidrios") y variantes buscadas por su atributo
  ("base arpege 1 lt").
- Orden: catálogo mayorista primero, después granel/a pedido, después lo que tiene stock.
"""
import logging
import re
import unicodedata

from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

# Sinónimos del rubro para que la búsqueda sea INTERPRETATIVA: el cliente usa
# una palabra y el producto está cargado con otra (ej: "perfume textil" →
# "Perfume p/ropa"). Se expande la búsqueda con estos equivalentes.
SYNONYMS = {
    'textil': ['ropa'], 'ropa': ['textil'],
    'hipoclorito': ['lavandina'], 'lavandina': ['hipoclorito'],
    'lavavajilla': ['detergente'], 'lavavajillas': ['detergente'],
    'lavaplatos': ['detergente'], 'platos': ['detergente'],
    'aromatizante': ['perfume', 'aroma'], 'aroma': ['aromatizante', 'perfume'],
    'blanqueador': ['optico', 'blanq'], 'optico': ['blanqueador'],
    # Pisos: "perfumina/desodorante/desod/limpiador perfumado" → Limpiador Desod.
    # (NO "Perfume p/ropa", que es para la ropa).
    'perfumina': ['limpiador desod', 'desod'],
    'desodorante': ['desod'], 'desod': ['desodorante', 'limpiador desod'],
    'desinfectante': ['desinf'],
    'quitasarro': ['quita sarro', 'sarro'], 'sarro': ['quita sarro'],
    'quitamanchas': ['quitamanchas', 'manchas'],
    'limpiavidrios': ['limpia vidrios', 'vidrios'], 'vidrios': ['limpia vidrios'],
    'manos': ['mano'], 'jabon': ['jabón'], 'jabón': ['jabon'],
    'suavizante': ['suav'], 'concentrado': ['base'], 'base': ['base', 'concentrad'],
}

# Palabras que no distinguen un producto (para buscar en el catálogo mayorista
# por la palabra clave real: "jabón líquido para ropa" → "jabon").
GENERIC_WORDS = {
    'liquido', 'liquida', 'liquidos', 'liquidas', 'para', 'de', 'del', 'la', 'el',
    'los', 'las', 'x', 'por', 'en', 'con', 'y', 'ropa', 'granel', 'precio',
    'precios', 'litro', 'litros', 'lt', 'lts', 'bidon', 'bidones', 'producto',
    'productos', 'mayorista', 'que', 'tenes', 'tienen', 'hay', 'piso', 'pisos',
    'un', 'una', 'unos', 'unas', 'al', 'sale', 'cuanto', 'cuánto', 'vale',
    'nº', 'n°', 'no', 'num', 'nro', 'numero', 'número', 'tamaño', 'tamano', 'medida',
}


def distinct_tokens(words):
    """Palabras que distinguen un producto: sin genéricas; los números se conservan."""
    return [w for w in words
            if (w.isdigit() or len(w) > 2) and _strip_accents(w).lower() not in GENERIC_WORDS]
# Rubros de fabricación propia: se producen a pedido, el stock no frena la venta.
MADE_TO_ORDER_CATEG = re.compile(r'^(Fabricaci[oó]n|Fraccionado)', re.I)
MAX_LIMIT = 15


def _strip_accents(txt):
    txt = unicodedata.normalize('NFKD', txt or '')
    return ''.join(c for c in txt if not unicodedata.combining(c))


def _norm(txt):
    return re.sub(r'[^a-z0-9]', '', _strip_accents(txt or '').lower())


NUM_TOKEN_RE = re.compile(r'^(?:n[º°o.]?\s*)?(\d+)$', re.I)   # "7", "nº7", "n°7", "N7"


def query_tokens(query):
    """Palabras útiles de una consulta: las de 2+ letras y los NÚMEROS sueltos (un "7"
    o un "5" distinguen la variante: Lampazo Nº7, Bidón 5 lts)."""
    out = []
    for w in (query or '').split():
        m = NUM_TOKEN_RE.match(w)
        if m:
            out.append(m.group(1))
        elif len(w) > 1:
            out.append(w)
    return out


def _word_domain(word):
    """Dominio para una palabra: nombre, código o valor de variante (aroma, tamaño),
    sin importar acentos ('jabón' → jabón | jabon). Un número corto ("7", "15") solo
    se busca en las variantes y en el nombre, nunca en el código (DA0467 tiene un 7)."""
    if word.isdigit() and len(word) <= 2:
        leaves = [('product_template_variant_value_ids.name', 'ilike', word),
                  ('name', 'ilike', word)]
        return ['|'] * (len(leaves) - 1) + leaves
    plain = _strip_accents(word)
    variants = [word] if plain.lower() == word.lower() else [word, plain]
    leaves = []
    for w in variants:
        leaves += [('name', 'ilike', w), ('default_code', 'ilike', w),
                   ('product_template_variant_value_ids.name', 'ilike', w)]
    return ['|'] * (len(leaves) - 1) + leaves


def variant_score(product, tokens):
    """Cuántos tokens de la consulta coinciden con la variante del producto. Un valor
    exacto ("7" = "Nº7", "5lts" = "5 lts") vale 3; contenido ("5" dentro de "Nº15"), 1."""
    vals = [_norm(v) for v in product.product_template_variant_value_ids.mapped('name')]
    label = ''.join(vals)
    score = 0
    for t in tokens:
        if not t:
            continue
        # v1.72: "Nº5" normalizado queda "no5" (º → o): hay que sacar "n", "no" o "nro".
        if any(v == t or re.sub(r'^n(?:ro|o)?', '', v) == t for v in vals):
            score += 3
        elif t in label:
            score += 1
    return score


def is_made_to_order(product):
    """True si lo fabricamos nosotros: granel (por litro), bases, fraccionado."""
    # display_name incluye la variante ("Lavandina (granel)"); name es solo el template.
    name = (product.display_name or product.name or '').lower()
    uom = (product.uom_id.name or '').lower() if product.uom_id else ''
    categ = product.categ_id.complete_name or ''
    return ('granel' in name) or uom in ('l', 'lt', 'litro', 'litros', 'l.') \
        or bool(MADE_TO_ORDER_CATEG.search(categ))


def is_granel(product):
    """True si se vende por litro en bidones (nombre, variante o unidad)."""
    name = (product.display_name or product.name or '').lower()
    uom = (product.uom_id.name or '').lower() if product.uom_id else ''
    return ('granel' in name) or uom in ('l', 'lt', 'litro', 'litros', 'l.')


def variant_label(product):
    vals = product.product_template_variant_value_ids
    return ', '.join(vals.mapped('name')) if vals else ''


@ToolRegistry.register
class SearchProducts(AgentTool):
    name = "search_products"
    description = (
        "Busca productos (product.product) en el catálogo por nombre, código, aroma o "
        "tamaño. Devuelve el nombre COMPLETO (con aroma y tamaño si es una variante), código, "
        "precio de la Lista Mayorista, unidad, si se fabrica a pedido (SIEMPRE cotizable) o "
        "el stock si es un producto de distribución. Útil para '¿tenés blem?', '¿cuánto sale "
        "la lavandina?', 'base desodorante arpege 1 litro'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Término de búsqueda (nombre o parte del nombre, código, aroma, tamaño).",
            },
            "partner_id": {
                "type": "integer",
                "description": "Si lo pasás, calcula el precio según la pricelist del cliente.",
            },
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    }

    # ───────────────────────── Búsqueda ─────────────────────────
    def _search(self, Product, query, limit):
        """(products, approximate)."""
        exact = Product.search(['|', ('barcode', '=', query), ('default_code', '=', query)],
                               limit=limit)
        if exact:
            return exact, False
        words = query_tokens(query)
        if not words:
            return Product.search(['|', ('name', 'ilike', query),
                                   ('default_code', 'ilike', query)], limit=limit), False

        # 1) Todas las palabras (nombre, código o variante), en cualquier orden.
        domain = [('sale_ok', '=', True)]
        for w in words:
            domain += _word_domain(w)
        products = Product.search(domain, limit=limit)
        if products:
            # v1.72 — Un producto que justo tiene todas las palabras no puede tapar al
            # catálogo mayorista. Caso real (12/11/2026): al cargarse "Dispenser Jabón
            # Líquido" y "SEIQ (jabón líquido p/ ropa)", pedir "jabón líquido" dejó de traer
            # los jabones a granel; y "quitasarro" traía solo "Dwc-100: Quitasarro y Óxido"
            # y no el "Quita Sarro" a granel. Se suman los del catálogo que coinciden por la
            # palabra distintiva o escritos separado; el orden final pone el catálogo primero.
            catalog = [('sale_ok', '=', True), ('product_tmpl_id.is_mayorista_catalog', '=', True)]
            extra = Product.browse()
            distinct = distinct_tokens(words)
            if distinct and len(distinct) < len(words):
                d = list(catalog)
                for w in distinct:
                    d += _word_domain(w)
                extra |= Product.search(d, limit=limit)
            compact = _norm(' '.join(distinct or words))
            if len(compact) >= 5:
                pool = Product.search(catalog + [('name', 'ilike', compact[:4])], limit=500)
                extra |= pool.filtered(lambda p: compact in _norm(p.name))
            return (extra | products)[:limit * 2] if extra else products, False

        # 2) Palabras distintivas solamente ("desod de pisos" → "desod"; "lampazo numero 7"
        #    → "lampazo 7").
        distinct = distinct_tokens(words)
        if distinct and len(distinct) < len(words):
            domain = [('sale_ok', '=', True)]
            for w in distinct:
                domain += _word_domain(w)
            products = Product.search(domain, limit=limit)
            if products:
                return products, False

        # 3) Palabras pegadas: "quitasarro" encuentra "Quita Sarro"; "limpiavidrios",
        #    "Limpia Vidrios". Se compara el nombre sin espacios ni acentos.
        compact = _norm(' '.join(distinct or words))
        if len(compact) >= 5:
            pool = Product.search([('sale_ok', '=', True), ('name', 'ilike', compact[:4])],
                                  limit=1000)
            hits = pool.filtered(lambda p: compact in _norm(p.name)
                                 or (len(_norm(p.name)) >= 5 and _norm(p.name) in compact))
            if hits:
                return hits[:limit], True

        # 4) Sinónimos (OR) y, si sigue vacío, la palabra más larga sola.
        expanded = set(w.lower() for w in (distinct or words))
        for w in list(expanded):
            for syn in SYNONYMS.get(_strip_accents(w).lower(), []):
                expanded.add(syn)
        terms = [w for w in expanded if len(w) > 2]
        if terms:
            leaves = [('name', 'ilike', w) for w in terms]
            products = Product.search([('sale_ok', '=', True)] + ['|'] * (len(leaves) - 1)
                                      + leaves, limit=limit)
            if products:
                return products, True
        key = max(distinct or words, key=len)
        return Product.search([('sale_ok', '=', True), ('name', 'ilike', key)],
                              limit=limit), True

    def _execute(self, env, run=None, query=None, partner_id=None, limit=10, **kwargs):
        if not query:
            return {"error": "query es obligatorio"}
        Product = env['product.product'].sudo()
        query = query.strip()
        limit = max(1, min(int(limit or 10), MAX_LIMIT))

        products, approximate = self._search(Product, query, limit * 3)

        # Orden: la variante que nombró ("7", "5 lts", "arpege") → catálogo mayorista →
        # a pedido (granel/fabricación) → con stock → resto.
        toks = [_norm(w) for w in query_tokens(query)]

        def rank(p):
            mto = is_made_to_order(p)
            has_stock = (not p.is_storable) or (p.qty_available or 0.0) > 0
            return (-variant_score(p, toks), not p.product_tmpl_id.is_mayorista_catalog,
                    not mto, not has_stock, p.name or '')
        products = products.sorted(rank)[:limit]

        pricelist = env['product.pricelist'].sudo().search(
            [('name', '=', 'Lista Mayorista')], limit=1)
        if not pricelist and partner_id:
            partner = env['res.partner'].sudo().browse(int(partner_id))
            if partner.exists() and partner.property_product_pricelist:
                pricelist = partner.property_product_pricelist

        results, sin_precio = [], []
        for p in products:
            price = p.list_price
            if pricelist:
                try:
                    pi = pricelist._get_product_price(p, 1.0)
                    price = pi if isinstance(pi, (int, float)) else p.list_price
                except Exception:
                    price = p.list_price
            mto = is_made_to_order(p)
            try:
                qty = p.qty_available or 0.0
            except Exception:
                qty = 0.0
            if price <= 1.0:
                sin_precio.append(p.display_name)
            results.append({
                'id': p.id,
                'name': p.display_name,
                'variant': variant_label(p),
                'default_code': p.default_code or '',
                'price': round(price, 2),
                'pricelist': pricelist.name if pricelist else 'list_price',
                'uom': p.uom_id.name if p.uom_id else '',
                'a_pedido': mto,
                'disponible': ('se fabrica a pedido: SIEMPRE se puede cotizar' if mto
                               else ('sin seguimiento de stock' if not p.is_storable
                                     else f'{qty:g} en stock')),
                'qty_available': None if mto else qty,
                'is_mayorista_catalog': bool(p.product_tmpl_id.is_mayorista_catalog),
                'sin_precio': price <= 1.0,
            })

        msg = []
        if not results:
            msg.append(
                f"No encontré productos que matcheen '{query}'. OJO: NO le digas al cliente "
                f"'no tenemos'. Probá otra palabra (sin marca, en singular) y, si sigue sin "
                f"aparecer, decile que ese producto no está en la lista, ofrecé lo más parecido "
                f"y escalá a Joaco UNA vez con todas las consultas juntas.")
        elif approximate:
            msg.append(
                f"No hubo match EXACTO de '{query}'; estos se parecen (sinónimos/palabra "
                f"clave). ELEGÍ el que claramente es lo que pidió y ofrecéselo. NO escales ni "
                f"digas 'no tenemos' por una diferencia de palabras.")
        if any(r['a_pedido'] for r in results):
            msg.append(
                "A PEDIDO: los productos marcados a_pedido=true (granel, bases, fraccionado) "
                "los fabricamos nosotros: se cotizan y se venden SIEMPRE, aunque figure 0 de "
                "stock. NUNCA digas que no hay stock de un producto a pedido.")
        if len({r['name'].split('(')[0] for r in results}) < len(results) \
                or any(r['variant'] for r in results):
            msg.append(
                "VARIANTES: hay productos con el mismo nombre y distinto aroma o tamaño "
                "(campo variant). Antes de cotizar confirmá con el cliente CUÁL (ej. 'Arpege, "
                "1 lt') y pasá ese product_id exacto a create_sale_order.")
        if sin_precio:
            msg.append(
                f"SIN PRECIO CARGADO (precio ≤ $1, no lo digas): {', '.join(sin_precio[:4])}. "
                f"Para esos consultá a Joaco el precio; no inventes ni uses otro.")
        if any('granel' in (r['name'] or '').lower() for r in results):
            config = env['cristal.agent.config'].sudo().get_active()
            price = config.bidon_price if config else 3500.0
            price_txt = '${:,.0f}'.format(price).replace(',', '.')
            msg.append(
                "BIDONES: el granel va en bidones de 20 L con recambio: por cada bidón lleno "
                "el cliente entrega uno vacío de 20 L con tapa (si se lo enviamos, al recibir "
                "el pedido; si retira, en la planta). Si no tiene vacíos para canjear, cada "
                f"bidón nuevo sale {price_txt}. Decíselo SIEMPRE cuando hables de granel.")
        if results:
            msg.append(
                "PRECIOS: decí SOLO precios de productos que aparecen en ESTA lista, con ESTE "
                "precio. Si el cliente pide una marca que no está (Lysoform, Poett, Ultra, "
                "Ala…), NO escales: ofrecé el equivalente nuestro de la lista. Ofrecé primero "
                "los del catálogo mayorista (is_mayorista_catalog=true).")

        return {
            "ok": True,
            "count": len(results),
            "products": results,
            "approximate": approximate,
            "search_terms": query.split(),
            "message_for_bot": ' '.join(msg) or None,
        }
