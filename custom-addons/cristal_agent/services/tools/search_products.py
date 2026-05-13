# -*- coding: utf-8 -*-
"""Tool: search_products — busca productos en el catálogo."""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


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
        if not exact:
            words = [w for w in query.split() if len(w) > 1]
            if words:
                word_domain = []
                for w in words:
                    word_domain.append(('name', 'ilike', w))
                products = Product.search(word_domain, limit=int(limit or 10))
            else:
                # query de 1 letra: usar ilike directo
                products = Product.search([
                    '|', ('name', 'ilike', query),
                    ('default_code', 'ilike', query),
                ], limit=int(limit or 10))
        else:
            products = exact

        # Pricelist del partner
        pricelist = None
        if partner_id:
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

        # Mensaje útil para el bot si encontró 0
        msg = None
        if not results:
            msg = (
                f"No encontré productos que matcheen '{query}'. "
                f"OJO: NO le digas al cliente 'no tenemos'. "
                f"ESCALA a Joaco con escalate_to_joaco preguntando si tenemos este producto "
                f"(puede existir con otro nombre, o haber que crearlo)."
            )

        return {
            "ok": True,
            "count": len(results),
            "products": results,
            "search_terms": query.split(),
            "message_for_bot": msg,
        }
