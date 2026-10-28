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

        # Combos publicados que contienen cada producto, del más caro al más barato
        combos_of = defaultdict(list)
        for combo in published.filtered(lambda t: t.type == 'combo').sorted('list_price', reverse=True):
            for tmpl in combo.combo_ids.combo_item_ids.product_id.product_tmpl_id:
                combos_of[tmpl.id].append(combo)

        # Sugerencias de la caja agrupadas por producto
        sizes, complements = defaultdict(list), defaultdict(list)
        for s in self.sudo().search([('active', '=', True)], order='manual desc, score desc'):
            target = s.product_id
            if not target or target.product_tmpl_id.id not in pub_ids:
                continue
            key = s.trigger_product_id.product_tmpl_id.id
            if s.kind == 'size':
                sizes[key].append(target.product_tmpl_id)
            else:
                if target.product_tmpl_id.id != key:
                    complements[key].append(target)

        # Primera vez: lo que ya estaba cargado a mano queda protegido
        Param = self.env['ir.config_parameter'].sudo()
        if not Param.get_param('cristal_venta_guiada.web_sync_initialized'):
            Template.search([('id', 'in', list(pub_ids)), '|', '|',
                             ('optional_product_ids', '!=', False),
                             ('alternative_product_ids', '!=', False),
                             ('accessory_product_ids', '!=', False)]).write({'cristal_web_manual': True})
            Param.set_param('cristal_venta_guiada.web_sync_initialized', fields.Datetime.now())

        def same_company(tmpl, records):
            # Un producto sin empresa no puede sugerir productos de una empresa (y al revés
            # solo los de la misma): Odoo lo rechaza.
            return [r for r in records if not r.company_id or r.company_id == tmpl.company_id]

        updated = 0
        for tmpl in published.filtered(lambda t: not t.cristal_web_manual and t.type != 'combo'):
            # Si el tamaño grande es otra variante del mismo producto, ya se elige en la ficha
            bigger = same_company(tmpl, [t for t in dict.fromkeys(sizes.get(tmpl.id, [])) if t != tmpl])[:1]
            optional = same_company(tmpl, combos_of.get(tmpl.id, [])[:2] + bigger)[:MAX_OPTIONAL]
            accessory = same_company(tmpl, list(dict.fromkeys(complements.get(tmpl.id, []))))[:MAX_ACCESSORY]
            vals = {}
            if [t.id for t in optional] != tmpl.optional_product_ids.ids:
                vals['optional_product_ids'] = [(6, 0, [t.id for t in optional])]
            if [t.id for t in bigger] != tmpl.alternative_product_ids.ids:
                vals['alternative_product_ids'] = [(6, 0, [t.id for t in bigger])]
            if [p.id for p in accessory] != tmpl.accessory_product_ids.ids:
                vals['accessory_product_ids'] = [(6, 0, [p.id for p in accessory])]
            if vals:
                try:
                    with self.env.cr.savepoint():
                        tmpl.write(vals)
                    updated += 1
                except Exception as e:  # noqa: BLE001 — un producto raro no frena al resto
                    _logger.warning("venta guiada: no pude actualizar la web de %s: %s", tmpl.display_name, e)

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
        _logger.info("venta guiada: web actualizada (%s productos con sugerencias nuevas, %s ordenados)",
                     updated, len(published))
