# -*- coding: utf-8 -*-
"""Tool: search_products — busca productos en el catálogo."""
import logging
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
    'piso': ['pisos'], 'pisos': ['piso'],
    'manos': ['mano'], 'jabon': ['jabón'], 'jabón': ['jabon'],
}


@ToolRegistry.register
class SearchProducts(AgentTool):
    name = "search_products"
    description = (
        "Busca productos (product.product) en el catálogo. Por nombre, código o id. "
        "Devuelve nombre, default_code, precio según pricelist (si pasás partner_id), "
        "stock disponible y unidad de medida. "
        "Útil para responder consultas tipo '¿tenés blem?' o '¿cuánto sale lavandina 20L?'"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Término de búsqueda (nombre o parte del nombre, código).",
            },
            "partner_id": {
                "type": "integer",
                "description": "Si lo pasás, calcula el precio según la pricelist del cliente.",
            },
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    }

    def _execute(self, env, run=None, query=None, partner_id=None, limit=10, **kwargs):
        if not query:
            return {"error": "query es obligatorio"}

        Product = env['product.product'].sudo()
        query = query.strip()

        # Estrategia 1: match exacto por código de barras o código interno
        exact = Product.search([
            '|',
            ('barcode', '=', query),
            ('default_code', '=', query),
        ], limit=int(limit or 10))

        # Estrategia 2: búsqueda por palabras separadas — TODAS deben aparecer
        # en el name (en cualquier orden). Esto resuelve casos como "Ariel granel"
        # que no haría match con "Detergente Ariel a Granel 200L" con ilike directo.
        approximate = False
        words = [w for w in query.split() if len(w) > 1]
        if exact:
            products = exact
        elif words:
            word_domain = [('name', 'ilike', w) for w in words]
            products = Product.search(word_domain, limit=int(limit or 10))
        else:
            # query de 1 letra: usar ilike directo
            products = Product.search([
                '|', ('name', 'ilike', query),
                ('default_code', 'ilike', query),
            ], limit=int(limit or 10))

        # Estrategia 3 — FALLBACK INTERPRETATIVO. Si el match exacto de TODAS las
        # palabras no dio nada, relajamos para no fallar por diferencias de
        # wording (ej: cliente pide "perfume textil" y el producto es "Perfume
        # p/ropa"). (a) expandimos con sinónimos y buscamos con OR; (b) si sigue
        # vacío, buscamos por la palabra más significativa sola. Marcamos los
        # resultados como aproximados para que el bot elija el que corresponde.
        if not exact and not products and words:
            approximate = True
            expanded = set(w.lower() for w in words)
            for w in list(expanded):
                for syn in SYNONYMS.get(w, []):
                    expanded.add(syn)
            terms = [w for w in expanded if len(w) > 2]
            if terms:
                or_domain = ['|'] * (len(terms) - 1) + [('name', 'ilike', w) for w in terms]
                products = Product.search(
                    [('sale_ok', '=', True)] + or_domain, limit=int(limit or 10))
            if not products:
                key = max(words, key=len)
                products = Product.search(
                    [('sale_ok', '=', True), ('name', 'ilike', key)], limit=int(limit or 10))

        # Pricelist: este bot es mayorista, así que el precio que cotizamos es el
        # de 'Lista Mayorista'. Si no existe, caemos a la del partner / list_price.
        pricelist = env['product.pricelist'].sudo().search(
            [('name', '=', 'Lista Mayorista')], limit=1)
        if not pricelist and partner_id:
            partner = env['res.partner'].sudo().browse(int(partner_id))
            if partner.exists() and partner.property_product_pricelist:
                pricelist = partner.property_product_pricelist

        results = []
        for p in products:
            price = p.list_price
            if pricelist:
                try:
                    price_info = pricelist._get_product_price(p, 1.0)
                    price = price_info if isinstance(price_info, (int, float)) else p.list_price
                except Exception:
                    price = p.list_price

            qty_available = 0.0
            try:
                qty_available = p.qty_available or 0.0
            except Exception:
                pass

            results.append({
                'id': p.id,
                'name': p.name,
                'default_code': p.default_code or '',
                'price': round(price, 2),
                'pricelist': pricelist.name if pricelist else 'list_price',
                'qty_available': qty_available,
                'uom': p.uom_id.name if p.uom_id else '',
                'is_mayorista_catalog': bool(p.product_tmpl_id.is_mayorista_catalog),
            })

        # Mensaje útil para el bot
        msg = None
        if not results:
            msg = (
                f"No encontré productos que matcheen '{query}'. "
                f"OJO: NO le digas al cliente 'no tenemos'. "
                f"ESCALA a Joaco con escalate_to_joaco preguntando si tenemos este producto "
                f"(puede existir con otro nombre, o haber que crearlo)."
            )
        elif approximate:
            msg = (
                f"No hubo match EXACTO de '{query}', pero estos productos se parecen "
                f"(búsqueda relajada por sinónimos/palabra clave). ELEGÍ el que "
                f"claramente es lo que pidió el cliente (ej: 'perfume textil' = "
                f"'Perfume p/ropa', 'lavavajilla' = 'Detergente') y ofrecéselo. "
                f"NO escales ni digas 'no tenemos' por una diferencia de palabras."
            )

        return {
            "ok": True,
            "count": len(results),
            "products": results,
            "approximate": approximate,
            "search_terms": query.split(),
            "message_for_bot": msg,
        }
