# -*- coding: utf-8 -*-
"""La escalera de la caja, en la tienda web (Joaco, 29/10/2026: "cuando agregan al carrito
que se despliegue el popup de aumentar el ticket y que en el carrito aparezcan los de cross").

- Al agregar: combo más grande que incluye el producto → "llevando N" → tamaño más grande →
  complemento. Un paso por vez, en nuestro popup (los nativos de Odoo quedaron de baja).
- En el carrito: los complementos de lo que lleva, y el combo que casi completa.
Todo lo que se muestra y se acepta se registra en cristal.vg.event (canal web) y alimenta
el recálculo nocturno de sugerencias, igual que la caja.
"""
import re

from odoo import api, models

CF_WEBSITE_ID = 1
MAX_CART_SUGGESTIONS = 4


def _clean(product):
    return re.sub(r'^\[[^\]]*\]\s*', '', product.display_name or '')


def _base(product):
    return re.sub(r'\s*\([^)]*\)\s*$', '', _clean(product)).strip().lower()


SIZE_RE = re.compile(r'(\d+(?:[.,]\d+)?)\s*(lts?\b|litros?\b|l\b|cc\b|ml\b|kg\b|kilos?\b)', re.I)


def _liters(product):
    m = SIZE_RE.search(_clean(product).lower())
    if not m:
        return None
    value = float(m.group(1).replace(',', '.'))
    return value / 1000.0 if m.group(2).lower() in ('cc', 'ml') else value


class CristalVgSuggestion(models.Model):
    _inherit = 'cristal.vg.suggestion'

    # ── Helpers ───────────────────────────────────────────────────
    @api.model
    def _web_price(self, order, product):
        pricelist = order.pricelist_id if order else False
        return pricelist._get_product_price(product, 1.0) if pricelist else product.lst_price

    @api.model
    def _web_sellable(self, website, product, company):
        tmpl = product.product_tmpl_id
        if not (product.sale_ok and tmpl.is_published and tmpl.website_id.id in (website.id, False)):
            return False
        if product.company_id and company and product.company_id != company:
            return False
        if tmpl.is_storable and not tmpl.allow_out_of_stock_order and product.free_qty <= 0:
            return False
        return True

    @api.model
    def _web_product(self, order, product, qty=1):
        return {
            'id': product.id,
            'name': _clean(product),
            'image': '/web/image/product.product/%s/image_256' % product.id,
            'url': product.product_tmpl_id.website_url,
            'price': self._web_price(order, product),
            'qty': qty,
        }

    # ── Al agregar al carrito ─────────────────────────────────────
    @api.model
    def website_ladder(self, order, product, line_id=None):
        website = order.website_id or self.env['website'].get_current_website()
        company = order.company_id
        cart_pids = set(order.order_line.product_id.ids)
        line = order.order_line.filtered(lambda l: l.id == line_id) if line_id else \
            order.order_line.filtered(lambda l: l.product_id == product and not l.combo_item_id)[:1]
        unit = self._web_price(order, product)
        steps = []

        # 1) El combo más grande (más caro) que incluye el producto o su versión en otro tamaño
        combos = self.env['product.template'].sudo().search([
            ('type', '=', 'combo'), ('is_published', '=', True), ('sale_ok', '=', True),
            ('website_id', 'in', [website.id, False])])
        for combo in combos.sorted('list_price', reverse=True):
            items = combo.combo_ids.combo_item_ids.product_id
            if product.product_tmpl_id not in items.product_tmpl_id:
                continue
            combo_variant = combo.product_variant_id
            price = self._web_price(order, combo_variant)
            loose = sum(min(self._web_price(order, p) for p in c.combo_item_ids.product_id) for c in combo.combo_ids
                        if c.combo_item_ids)
            if loose <= price:
                continue
            steps.append({
                'kind': 'combo', 'title': 'Con esto armás un combo',
                'text': 'Llevate el %s: %d productos por $%s (suelto $%s). Ahorrás $%s.' % (
                    combo.name, len(combo.combo_ids), f'{price:,.0f}', f'{loose:,.0f}', f'{loose - price:,.0f}'),
                'cta': 'Ver el combo', 'product': self._web_product(order, combo_variant),
                'saving': loose - price,
            })
            break

        # 2) Llevando N (precio por cantidad de la lista)
        if order.pricelist_id:
            tier = self.env['product.pricelist.item'].sudo().search([
                ('pricelist_id', '=', order.pricelist_id.id), ('product_id', '=', product.id),
                ('compute_price', '=', 'fixed'), ('min_quantity', '>=', 2), ('min_quantity', '<=', 6)],
                order='min_quantity', limit=1)
            if tier and tier.fixed_price < unit and (not line or line.product_uom_qty < tier.min_quantity):
                n = int(tier.min_quantity)
                steps.append({
                    'kind': 'qty', 'title': 'Llevando %d, más barato' % n,
                    'text': 'Llevando %d te sale $%s cada uno en vez de $%s. Ahorrás $%s.' % (
                        n, f'{tier.fixed_price:,.0f}', f'{unit:,.0f}', f'{(unit - tier.fixed_price) * n:,.0f}'),
                    'cta': 'Llevar %d' % n, 'product': self._web_product(order, product, n),
                    'qty': n, 'line_id': line.id if line else False, 'saving': (unit - tier.fixed_price) * n,
                })

        # 3) Tamaño más grande y 4) complemento, de las sugerencias de la caja
        suggestions = self.sudo().search([('trigger_product_id', '=', product.id), ('active', '=', True)],
                                         order='manual desc, score desc')
        # El tamaño SIGUIENTE (1 L → 5 L, 5 L → 10 L), nunca el más grande de una (Joaco 30/10).
        sizes = [s for s in suggestions if s.kind == 'size' and s.product_id.id not in cart_pids
                 and self._web_sellable(website, s.product_id, company)]
        size = min(sizes, key=lambda s: _liters(s.product_id) or 0, default=None) if sizes else None
        if size:
            big, big_price = size.product_id, self._web_price(order, size.product_id)
            small_l, big_l = _liters(product), _liters(big)
            per_liter = ''
            if small_l and big_l and unit:
                pct = round(100 * (1 - (big_price / big_l) / (unit / small_l)))
                if pct > 0:
                    per_liter = ' Te sale %d%% menos el litro.' % pct
            steps.append({
                'kind': 'size', 'title': 'Te conviene el tamaño siguiente',
                'text': '%s a $%s: rinde mucho más que el de %s.%s' % (
                    _clean(big), f'{big_price:,.0f}', _clean(product).split('(')[-1].rstrip(')') or 'este', per_liter),
                'cta': 'Cambiar por el grande', 'product': self._web_product(order, big),
                'replace_line_id': line.id if line else False,
            })
        comp = next((s for s in suggestions if s.kind != 'size' and s.product_id.id not in cart_pids
                     and s.product_id.product_tmpl_id != product.product_tmpl_id
                     and self._web_sellable(website, s.product_id, company)), None)
        if comp:
            steps.append({
                'kind': 'complement', 'title': 'Se lleva junto',
                'text': 'Los que llevan %s suelen sumar %s ($%s).' % (
                    _clean(product), _clean(comp.product_id), f'{self._web_price(order, comp.product_id):,.0f}'),
                'cta': 'Agregar', 'product': self._web_product(order, comp.product_id),
            })
        for step in steps:
            for key in ('text', 'title'):
                step[key] = step[key].replace(',', '.')
        return steps

    # ── En el carrito ─────────────────────────────────────────────
    @api.model
    def website_cart_suggestions(self, order):
        """{'products': [(product, price)], 'combo': {...} | None} para el carrito."""
        if not order or not order.order_line:
            return {'products': [], 'combo': None}
        website = order.website_id or self.env['website'].get_current_website()
        company = order.company_id
        cart = order.order_line.filtered(lambda l: l.product_id and not l.is_delivery and not l.combo_item_id)
        cart_tmpls = set(cart.product_id.product_tmpl_id.ids)
        seen, products = set(), []
        for s in self.sudo().search([('trigger_product_id', 'in', cart.product_id.ids), ('active', '=', True),
                                     ('kind', '!=', 'size')], order='manual desc, score desc'):
            p = s.product_id
            if p.product_tmpl_id.id in cart_tmpls or p.product_tmpl_id.id in seen:
                continue
            if not self._web_sellable(website, p, company):
                continue
            seen.add(p.product_tmpl_id.id)
            products.append((p, self._web_price(order, p), s.trigger_product_id.id))
            if len(products) >= MAX_CART_SUGGESTIONS:
                break
        # El combo que ya está a mitad de camino con lo que lleva
        best = None
        for combo in self.env['product.template'].sudo().search([
                ('type', '=', 'combo'), ('is_published', '=', True), ('website_id', 'in', [website.id, False])]):
            slots = [c.combo_item_ids.product_id.product_tmpl_id.ids for c in combo.combo_ids if c.combo_item_ids]
            matched = sum(1 for slot in slots if any(t in cart_tmpls for t in slot))
            if slots and matched * 2 >= len(slots):
                price = self._web_price(order, combo.product_variant_id)
                loose = sum(min(self._web_price(order, p) for p in c.combo_item_ids.product_id)
                            for c in combo.combo_ids if c.combo_item_ids)
                if loose > price and (not best or matched / len(slots) > best['ratio']):
                    best = {'template': combo, 'matched': matched, 'slots': len(slots), 'ratio': matched / len(slots),
                            'price': price, 'saving': loose - price, 'url': combo.website_url}
        return {'products': products, 'combo': best}

    @api.model
    def website_cart_popup(self, order):
        """Datos del popup "Completá tu compra" del carrito: sugerencias, combo a medio camino y
        cuánto falta para el envío gratis (lo que hacen las tiendas grandes: barra de envío gratis +
        "los que compraron esto también llevaron" + un clic para agregar)."""
        data = self.website_cart_suggestions(order)
        website = order.website_id or self.env['website'].get_current_website()
        products = [dict(self._web_product(order, p), trigger_id=trigger) for p, _price, trigger in data['products']]
        combo = data['combo'] and {
            'name': data['combo']['template'].name, 'matched': data['combo']['matched'], 'slots': data['combo']['slots'],
            'price': data['combo']['price'], 'saving': data['combo']['saving'], 'url': data['combo']['url'],
        }
        carriers = self.env['delivery.carrier'].sudo().search([
            ('website_published', '=', True), ('free_over', '=', True), ('website_id', 'in', [website.id, False])])
        free_over = min(carriers.mapped('amount')) if carriers else 0.0
        if hasattr(order, '_compute_amount_total_without_delivery'):
            subtotal = order._compute_amount_total_without_delivery()
        else:
            subtotal = order.amount_total - order.amount_delivery
        if products:
            self.env['cristal.vg.event'].sudo().log_events([{
                'order_uuid': 'web-%s' % order.id, 'trigger_product_id': p['trigger_id'] or False,
                'product_id': p['id'], 'kind': 'complement', 'channel': 'web',
            } for p in products])
        return {
            'order_id': order.id, 'cart_quantity': order.cart_quantity,
            'products': products, 'combo': combo,
            'free_over': free_over, 'subtotal': subtotal, 'missing': max(0.0, free_over - subtotal),
        }
