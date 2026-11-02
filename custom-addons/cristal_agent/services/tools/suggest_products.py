# -*- coding: utf-8 -*-
"""
Tool: suggest_products (v1.52)

Qué ofrecer para subir el ticket, con DATOS y no de memoria:
1. Lo que el cliente ya compró antes y no está en la cotización (reposición).
2. Lo que el motor de venta guiada (cristal_venta_guiada) calcula a partir de las
   canastas reales: tamaño que le conviene y complementos que se llevan juntos.
3. Si no hay datos, complementos por rubro (detergente → desengrasante, etc.).
Además devuelve cuánto le falta para el mínimo de compra y para el envío sin cargo.
Solo lee: no toca la cotización ni manda nada.
"""
import logging
import re

from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

# Complementos por rubro cuando no hay historia (palabra en el nombre → qué buscar).
FALLBACK_COMPLEMENTS = [
    (re.compile(r'detergente', re.I), ['desengrasante', 'lavandina']),
    (re.compile(r'jab[oó]n', re.I), ['suavizante', 'quitamanchas']),
    (re.compile(r'suavizante', re.I), ['jabón líquido', 'perfumina']),
    (re.compile(r'lavandina', re.I), ['limpiador', 'detergente']),
    (re.compile(r'piso|limpiador', re.I), ['desodorante de piso', 'cera']),
    (re.compile(r'desengrasante', re.I), ['detergente', 'limpia vidrios']),
]
EXCLUDED_NAME = re.compile(r'flete|bid[oó]n|muestra|combo', re.I)


def _clean(name):
    return re.sub(r'^\[[^\]]*\]\s*', '', name or '')


@ToolRegistry.register
class SuggestProducts(AgentTool):
    name = "suggest_products"
    description = (
        "Devuelve 1 a 3 productos para ofrecer ADEMÁS de lo que el cliente ya pidió, con "
        "precio mayorista y el motivo (lo que suele comprar y no pidió, lo que otros llevan "
        "junto, el tamaño que le conviene). También dice cuánto le falta para el mínimo de "
        "compra y para el envío sin cargo. Llamala DESPUÉS de create_sale_order (pasale "
        "order_id) o con product_ids si todavía no cotizaste. Ofrecé como máximo 2, en una "
        "línea, sin presionar. Solo lee: no modifica la cotización."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del cliente."},
            "order_id": {"type": "integer",
                         "description": "ID de la cotización (lo devuelve create_sale_order)."},
            "product_ids": {"type": "array", "items": {"type": "integer"},
                            "description": "Productos ya pedidos, si no hay cotización."},
            "limit": {"type": "integer", "default": 3},
        },
        "required": ["partner_id"],
    }

    def _execute(self, env, run=None, partner_id=None, order_id=None, product_ids=None,
                 limit=3, **kwargs):
        partner = env['res.partner'].sudo().browse(int(partner_id)).exists()
        if not partner:
            return {"error": f"partner_id={partner_id} no existe"}
        Product = env['product.product'].sudo()
        SO = env['sale.order'].sudo()
        config = env['cristal.agent.config'].sudo().get_active()
        limit = max(1, min(int(limit or 3), 5))

        order = SO.browse(int(order_id)).exists() if order_id else SO
        if not order:
            order = SO.search([('partner_id', '=', partner.id), ('state', 'in', ('draft', 'sent'))],
                              order='create_date desc', limit=1)
        in_quote = order.order_line.filtered(
            lambda l: not l.display_type and l.product_id).mapped('product_id') if order else Product
        if product_ids:
            in_quote |= Product.browse([int(i) for i in product_ids]).exists()
        in_ids = set(in_quote.ids)
        in_templates = set(in_quote.mapped('product_tmpl_id').ids)

        pricelist = env['product.pricelist'].sudo().search([('name', '=', 'Lista Mayorista')],
                                                            limit=1)

        def price_of(product):
            try:
                if pricelist:
                    return float(pricelist._get_product_price(product, 1.0))
            except Exception as e:
                _logger.debug("suggest_products: precio de %s falló: %s", product.id, e)
            return float(product.lst_price or 0.0)

        def sellable(product):
            return (product.sale_ok and product.active and product.id not in in_ids
                    and product.product_tmpl_id.id not in in_templates
                    and not EXCLUDED_NAME.search(product.name or '')
                    and (not product.is_storable or product.qty_available > 0))

        suggestions, seen = [], set()

        def add(product, kind, reason, text=None):
            if len(suggestions) >= limit or product.id in seen or not sellable(product):
                return
            seen.add(product.id)
            price = price_of(product)
            suggestions.append({
                'product_id': product.id, 'name': _clean(product.display_name),
                'price': round(price, 2), 'uom': product.uom_id.name, 'kind': kind,
                'reason': reason,
                'text': text or f"{_clean(product.display_name)} a ${price:,.0f} el {product.uom_id.name}".replace(',', '.'),
            })

        # 1) Lo que ya compró antes (últimos 180 días) y no está en la cotización.
        from datetime import timedelta
        from odoo import fields as _f
        since = _f.Datetime.now() - timedelta(days=180)
        past = SO.search([('partner_id', '=', partner.id), ('state', 'in', ('sale', 'done')),
                          ('date_order', '>=', since)], order='date_order desc', limit=10)
        qty_by_product = {}
        for o in past:
            for l in o.order_line.filtered(lambda x: not x.display_type and x.product_id):
                qty_by_product[l.product_id] = qty_by_product.get(l.product_id, 0.0) + l.product_uom_qty
        for product, qty in sorted(qty_by_product.items(), key=lambda kv: -kv[1]):
            add(product, 'habitual', f"lo compró antes ({qty:g} {product.uom_id.name} en 6 meses) y no lo pidió ahora",
                f"¿Repone también {_clean(product.display_name)}? La última vez llevó {qty:g} {product.uom_id.name}.")
            if len(suggestions) >= 2:
                break

        # 2) Venta guiada (canastas reales) si el módulo está instalado.
        if 'cristal.vg.suggestion' in env and in_ids:
            Sugg = env['cristal.vg.suggestion'].sudo()
            for sg in Sugg.search([('trigger_product_id', 'in', list(in_ids)), ('active', '=', True)],
                                  order='manual desc, score desc', limit=20):
                add(sg.product_id, sg.kind, sg.reason or sg.text or 'se lleva junto',
                    sg.text)
                if len(suggestions) >= limit:
                    break

        # 3) Complementos por rubro (sin historia).
        if len(suggestions) < 2 and in_quote:
            names = ' '.join(in_quote.mapped('name'))
            wanted = []
            for rx, comps in FALLBACK_COMPLEMENTS:
                if rx.search(names):
                    wanted += comps
            for term in wanted:
                cands = Product.search([('sale_ok', '=', True), ('name', 'ilike', term)], limit=20)
                cands = sorted(cands.filtered(sellable), key=lambda c: -(c.qty_available or 0.0))
                if cands:
                    add(cands[0], 'complement', f"complementa lo que lleva ({term})")
                if len(suggestions) >= limit:
                    break

        # 4) Brechas: mínimo de compra y envío sin cargo.
        gaps = {}
        if order:
            base = sum(order.order_line.filtered(
                lambda l: not l.display_type and l.product_id
                and not EXCLUDED_NAME.search(l.product_id.name or '')).mapped('price_subtotal'))
            gaps['subtotal_productos'] = round(base, 2)
            cso = ToolRegistry.get('create_sale_order')
            COMPRA_MIN = float(getattr(cso, 'COMPRA_MIN', 50000.0) or 50000.0)
            mode = getattr(order, 'cristal_delivery_mode', None)
            if mode != 'retiro':
                if partner.agent_zone == 'ruta_camion' or partner.truck_circuit_id:
                    min_order = config.route_min_order or 0.0
                    free_from = config.route_free_shipping_from or 0.0
                    if base < min_order:
                        gaps['falta_para_minimo'] = round(min_order - base, 2)
                    if free_from and base < free_from:
                        gaps['falta_para_envio_sin_cargo'] = round(free_from - base, 2)
                else:
                    if base < COMPRA_MIN:
                        gaps['falta_para_minimo'] = round(COMPRA_MIN - base, 2)

        return {"ok": True, "order_id": order.id if order else None,
                "suggestions": suggestions, "gaps": gaps,
                "note": ("Ofrecé como máximo 2 en UNA línea, con el precio tal cual viene acá. "
                         "Si hay 'falta_para_envio_sin_cargo', usalo de gancho.")}
