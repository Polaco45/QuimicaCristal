# -*- coding: utf-8 -*-
"""La web vende con la misma escalera que la caja (Joaco, 28/10/2026: "el catálogo de la
tienda tiene que estar ordenado todo con up y cross sell").

Cada noche, después de recalcular las sugerencias:
- Al agregar al carrito (optional_product_ids): el combo más grande que incluye el
  producto y el tamaño más grande.
- En la ficha (alternative_product_ids): el tamaño más grande.
- En el carrito (accessory_product_ids): los complementos que más se compran juntos.
- Orden del catálogo (website_sequence): combos primero (del más grande al más chico) y
  después lo que más se vende.
Los productos marcados "Sugerencias web a mano" no se tocan.
"""
import logging
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

CF_WEBSITE_ID = 1   # "Cristal" — www.quimicacristal.com.ar
CF_PRICELIST_ID = 19  # L.C 1, precio de consumidor final
QTY_RIBBON = 'Promo x 3'   # corto: en diagonal un texto largo se corta
MAX_OPTIONAL = 3
MAX_ACCESSORY = 3


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    cristal_web_manual = fields.Boolean(
        string='Sugerencias web a mano',
        help='Si está marcado, el recálculo nocturno no cambia los productos opcionales, '
             'alternativos ni accesorios de este producto en la web.')


class CristalVgSuggestion(models.Model):
    _inherit = 'cristal.vg.suggestion'

    @api.model
    def _cron_recompute(self, days=180):
        res = super()._cron_recompute(days=days)
        try:
            with self.env.cr.savepoint():
                self._cristal_sync_website(days)
        except Exception:  # noqa: BLE001 — la web no frena la caja
            _logger.exception("venta guiada: no pude actualizar la web")
        return res

    @api.model
    def _cristal_sync_website(self, days=180):
        Template = self.env['product.template'].sudo()
        if 'accessory_product_ids' not in Template._fields:
            return  # sin tienda online
        # Solo la tienda de consumidor final (quimicacristal.com.ar) y lo que no tiene sitio fijo
        published = Template.search([('is_published', '=', True), ('sale_ok', '=', True),
                                     ('website_id', 'in', [CF_WEBSITE_ID, False])])
        if not published:
            return
        pub_ids = set(published.ids)

        # Los opcionales/alternativos/accesorios nativos quedaron de baja (29/10/2026): la web usa
        # nuestro popup al agregar y nuestro bloque en el carrito (website_ladder.py).
        updated = self._cristal_clear_native_suggestions(published)

        # Orden del catálogo: combos primero, después lo más vendido
        since = fields.Datetime.now() - timedelta(days=days)
        sold = defaultdict(float)
        for model, qty_field, state in (('pos.order.line', 'qty', ('paid', 'done', 'invoiced')),
                                        ('sale.order.line', 'product_uom_qty', ('sale',))):
            for row in self.env[model].sudo().read_group(
                    [('order_id.date_order', '>=', since), ('order_id.state', 'in', state),
                     ('product_id.product_tmpl_id', 'in', list(pub_ids))],
                    ['product_id', qty_field], ['product_id']):
                product = self.env['product.product'].browse(row['product_id'][0])
                sold[product.product_tmpl_id.id] += row[qty_field] or 0
        combos = published.filtered(lambda t: t.type == 'combo').sorted('list_price', reverse=True)
        rest = (published - combos).sorted(lambda t: (-sold.get(t.id, 0), t.name or ''))
        for seq, tmpl in enumerate(combos, start=1):
            if tmpl.website_sequence != seq:
                tmpl.website_sequence = seq
        for seq, tmpl in enumerate(rest, start=100):
            if tmpl.website_sequence != seq:
                tmpl.website_sequence = seq
        self._cristal_sync_qty_ribbon(published)
        _logger.info("venta guiada: web actualizada (%s productos con sugerencias nuevas, %s ordenados)",
                     updated, len(published))

    @api.model
    def _cristal_clear_native_suggestions(self, published):
        """Saca los productos opcionales, alternativos y accesorios de Odoo (los popups viejos).
        Devuelve cuántos productos se limpiaron."""
        dirty = published.filtered(lambda t: t.optional_product_ids or t.alternative_product_ids
                                   or t.accessory_product_ids)
        for tmpl in dirty:
            try:
                with self.env.cr.savepoint():
                    tmpl.write({'optional_product_ids': [(5, 0, 0)], 'alternative_product_ids': [(5, 0, 0)],
                                'accessory_product_ids': [(5, 0, 0)]})
            except Exception as e:  # noqa: BLE001
                _logger.warning("venta guiada: no pude limpiar los sugeridos nativos de %s: %s", tmpl.display_name, e)
        return len(dirty)

    @api.model
    def _cristal_sync_qty_ribbon(self, published):
        """Cinta "Promo x 3" en la foto de los productos con precio por cantidad
        en la lista de consumidor final. Solo pone o saca la cinta nuestra."""
        if 'website_ribbon_id' not in published._fields or 'product.ribbon' not in self.env:
            return
        Ribbon = self.env['product.ribbon'].sudo()
        ribbon = Ribbon.search([('name', '=', QTY_RIBBON)], limit=1) or Ribbon.create(
            {'name': QTY_RIBBON, 'bg_color': '#f4b400', 'text_color': '#1d2433'})
        items = self.env['product.pricelist.item'].sudo().search([
            ('pricelist_id', '=', CF_PRICELIST_ID), ('applied_on', '=', '0_product_variant'),
            ('compute_price', '=', 'fixed'), ('min_quantity', '>=', 2), ('min_quantity', '<=', 6)])
        with_tier = set(items.product_id.product_tmpl_id.ids)
        for tmpl in published:
            if tmpl.id in with_tier and not tmpl.website_ribbon_id:
                tmpl.website_ribbon_id = ribbon
            elif tmpl.id not in with_tier and tmpl.website_ribbon_id == ribbon:
                tmpl.website_ribbon_id = False
