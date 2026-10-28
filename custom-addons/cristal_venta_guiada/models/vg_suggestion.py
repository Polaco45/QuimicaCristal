# -*- coding: utf-8 -*-
import logging
import math
import re
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Rubros que no se sugieren ni disparan sugerencias en el mostrador.
EXCLUDED_CATEG = re.compile(r'Materias Primas|Muestras|Combos y Kit', re.I)
EXCLUDED_NAME = re.compile(r'granel', re.I)
# Rubros líquidos donde tiene sentido ofrecer el tamaño más grande.
LIQUID_CATEG = re.compile(r'^(Fabricaci[oó]n|Fraccionado)|L[ií]quidos|Limpia Vidrios', re.I)
SIZE_RE = re.compile(r'(\d+(?:[.,]\d+)?)\s*(lts?|l|cc|ml)\b\.?', re.I)
CLASS_BOOST = {'ESTANCADO': 1.4, 'BAJA': 1.2, 'MEDIA': 1.0, 'ALTA': 1.0, 'QUIEBRE': 0.6}
# Productos de impulso por defecto cuando un rubro no tiene historia.
DEFAULT_IMPULSE_CATEG = ('Distribución / Esponjas', 'Fabricación / Limpiador Desinf Desod')


def _fmt(amount):
    return '$' + f'{int(round(amount)):,}'.replace(',', '.')


def _clean_name(product):
    return re.sub(r'^\[[^\]]*\]\s*', '', product.display_name or '')


class CristalVgSuggestion(models.Model):
    _name = 'cristal.vg.suggestion'
    _description = 'Venta guiada — sugerencia por producto'
    _order = 'trigger_product_id, manual desc, score desc, id'

    trigger_product_id = fields.Many2one('product.product', string='Producto cargado', required=True,
                                         index=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Producto sugerido', required=True,
                                 ondelete='cascade')
    kind = fields.Selection([
        ('size', 'Tamaño mayor'),
        ('complement', 'Complemento'),
        ('category', 'Respaldo categoría'),
        ('manual', 'Fijada a mano'),
    ], string='Tipo', required=True, default='manual')
    text = fields.Char(string='Texto para el vendedor')
    reason = fields.Char(string='Motivo (dato)')
    score = fields.Float(digits=(16, 4))
    manual = fields.Boolean(string='Fijada a mano', default=True,
                            help='Las fijadas a mano van primero y el recálculo nocturno no las borra.')
    active = fields.Boolean(default=True)

    # ------------------------------------------------------------------
    # Recálculo
    # ------------------------------------------------------------------
    @api.model
    def _cron_recompute(self, days=180):
        config = self.env['pos.config'].search([('cristal_vg_enabled', '=', True)], limit=1)
        if not config:
            _logger.info("venta guiada: no hay cajas con venta guiada, no recalculo")
            return
        result = self._compute_suggestions(config, days)
        Sugg = self.sudo()
        Sugg.search([('manual', '=', False)]).unlink()
        Sugg.create(result)
        _logger.info("venta guiada: %s sugerencias automáticas recalculadas", len(result))

    def action_recompute(self):
        self._cron_recompute()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def _vg_products(self, config):
        """Productos del POS con su precio de lista CF, stock, rotación y familia."""
        Product = self.env['product.product'].with_company(config.company_id)
        products = Product.search([
            ('available_in_pos', '=', True), ('sale_ok', '=', True), ('type', '!=', 'combo'),
        ])
        products = products.filtered(
            lambda p: not EXCLUDED_CATEG.search(p.categ_id.complete_name or '')
            and not EXCLUDED_NAME.search(p.name or ''))
        prices = config.pricelist_id._get_products_price(products, 1.0)
        since90 = fields.Datetime.now() - timedelta(days=90)
        sold = {
            product.id: qty for product, qty in self.env['stock.move']._read_group(
                [('state', '=', 'done'), ('location_dest_id.usage', '=', 'customer'),
                 ('date', '>=', since90), ('product_id', 'in', products.ids)],
                ['product_id'], ['product_uom_qty:sum'])
        }
        info = {}
        for p in products:
            price = prices.get(p.id) or 0.0
            if price <= 1:
                continue
            stock = p.qty_available
            s90 = sold.get(p.id, 0.0)
            if stock <= 0:
                cls = 'QUIEBRE'
            elif not s90:
                cls = 'ESTANCADO'
            else:
                cover = stock / (s90 / 90.0)
                cls = 'BAJA' if cover > 120 else 'ALTA' if cover <= 30 else 'MEDIA'
            net = price / 1.21
            margin = (net - p.standard_price) / net * 100 if net else 0.0
            name = _clean_name(p)
            low = name.lower()
            m = SIZE_RE.search(low)
            liters = None
            if m:
                value = float(m.group(1).replace(',', '.'))
                liters = value / 1000.0 if m.group(2).lower() in ('cc', 'ml') else value
            fam = re.sub(r'\s+', ' ', re.sub(r'[(),.:]', ' ', SIZE_RE.sub('', low).replace(' x ', ' '))).strip()
            base_fam = re.sub(r'\s+', ' ', re.sub(r'[^a-záéíóúñ ]', ' ', SIZE_RE.sub('', re.sub(r'\(.*\)', '', low)))).strip()
            info[p.id] = {
                'product': p, 'name': name, 'price': price, 'stock': stock, 's90': s90, 'cls': cls,
                'margin': max(margin, 5.0), 'liters': liters, 'fam': fam, 'base_fam': base_fam,
                'categ': p.categ_id.complete_name or '', 'liquid': bool(LIQUID_CATEG.search(p.categ_id.complete_name or '')),
            }
        return info

    @api.model
    def _vg_baskets(self, config, days):
        """Tickets de consumidor final (por posición fiscal) de los últimos `days` días."""
        since = fields.Datetime.now() - timedelta(days=days)
        domain = [('date_order', '>=', since), ('state', 'in', ('paid', 'done', 'invoiced')),
                  ('company_id', '=', config.company_id.id)]
        fps = config.cristal_vg_fiscal_position_ids
        if fps:
            domain.append(('fiscal_position_id', 'in', fps.ids))
        orders = self.env['pos.order'].search(domain)
        lines = self.env['pos.order.line'].search_read(
            [('order_id', 'in', orders.ids)], ['order_id', 'product_id', 'qty', 'refunded_orderline_id'], load=False)
        refunded_orders = set()
        bad_orders = set()
        for line in lines:
            if line['qty'] < 0:
                bad_orders.add(line['order_id'])
                if line['refunded_orderline_id']:
                    refunded_orders.add(line['refunded_orderline_id'])
        if refunded_orders:
            for line in self.env['pos.order.line'].browse(list(refunded_orders)):
                bad_orders.add(line.order_id.id)
        skip = {config[f].id for f in ('discount_product_id', 'tip_product_id') if f in config._fields} - {False}
        baskets = defaultdict(set)
        for line in lines:
            if line['order_id'] in bad_orders or line['product_id'] in skip or line['qty'] <= 0:
                continue
            baskets[line['order_id']].add(line['product_id'])
        return list(baskets.values())

    @api.model
    def _vg_feedback(self):
        """Factor por par (cargado, sugerido) según lo que aceptó la gente en 60 días."""
        since = fields.Datetime.now() - timedelta(days=60)
        factors = {}
        for trigger, product, accepted, count in self.env['cristal.vg.event']._read_group(
                [('date', '>=', since), ('trigger_product_id', '!=', False), ('product_id', '!=', False)],
                ['trigger_product_id', 'product_id', 'accepted'], ['__count']):
            key = (trigger.id, product.id)
            shown, acc = factors.get(key, (0, 0))
            factors[key] = (shown + count, acc + (count if accepted else 0))
        result = {}
        for key, (shown, acc) in factors.items():
            if shown < 8:
                continue
            rate = acc / shown
            result[key] = 0.3 if rate < 0.05 else 1.5 if rate > 0.30 else 1.0
        return result

    @api.model
    def _compute_suggestions(self, config, days=180):
        info = self._vg_products(config)
        baskets = self._vg_baskets(config, days)
        feedback = self._vg_feedback()
        total = len(baskets) or 1
        n = defaultdict(int)
        pair = defaultdict(lambda: defaultdict(int))
        cat_n = defaultdict(int)
        cat_pair = defaultdict(lambda: defaultdict(int))
        for basket in baskets:
            items = [pid for pid in basket if pid in info]
            for a in items:
                n[a] += 1
                for b in items:
                    if a != b:
                        pair[a][b] += 1
            cats = {info[pid]['categ'] for pid in items}
            for c in cats:
                cat_n[c] += 1
                for d in cats:
                    if c != d:
                        cat_pair[c][d] += 1

        def sellable(d):
            return d and d['stock'] > 0

        vals = []
        for pid, p in info.items():
            cands = []   # (kind, product_info, text, reason, score)

            # 1) Tamaño mayor con mejor precio por litro (mismo aroma; si no, otro aroma)
            if p['liters'] and p['liquid']:
                for key in ('fam', 'base_fam'):
                    bigger = sorted(
                        (q for q in info.values() if q['product'].id != pid and q[key] == p[key]
                         and q['liters'] and q['liters'] > p['liters'] and sellable(q)
                         and q['price'] / q['liters'] < 0.9 * p['price'] / p['liters']),
                        key=lambda q: (-q['liters'], -q['stock']))   # el más grande primero
                    if bigger:
                        q = bigger[0]
                        saving = round(100 * (1 - (q['price'] / q['liters']) / (p['price'] / p['liters'])))
                        cands.append(('size', q,
                                      f"¿Lo usás seguido? {q['name']} a {_fmt(q['price'])}: te sale {saving}% menos el litro.",
                                      f"$/L {_fmt(p['price'] / p['liters'])} contra {_fmt(q['price'] / q['liters'])}",
                                      10.0))
                        break

            # 2) Complementos según los tickets
            comps = []
            for qid, both in pair[pid].items():
                q = info.get(qid)
                if not sellable(q) or q['base_fam'] == p['base_fam'] or both < 2:
                    continue
                lift = both * total / (n[pid] * n[qid])
                if lift < 1.5:
                    continue
                conf = both / n[pid]
                score = conf * math.sqrt(min(lift, 10.0)) * CLASS_BOOST.get(q['cls'], 1.0) * (q['margin'] / 50.0)
                score *= feedback.get((pid, qid), 1.0)
                comps.append((score, q, both, conf, lift))
            for score, q, both, conf, lift in sorted(comps, key=lambda c: -c[0])[:2]:
                cands.append(('complement', q,
                              f"Los que llevan esto suelen sumar {q['name']}. ¿Te lo agrego? ({_fmt(q['price'])})",
                              f"{both} tickets juntos, {round(conf * 100)}% de los que llevan este, lift {lift:.1f}",
                              score))

            # 3) Respaldo por rubro afín: el mejor producto de impulso de ese rubro
            if len(cands) < 2:
                affine = []
                for d, both in cat_pair[p['categ']].items():
                    if both < 3:
                        continue
                    lift = both * total / (cat_n[p['categ']] * cat_n[d])
                    if lift >= 1.3:
                        affine.append((lift * math.sqrt(both), d, lift))
                pool = [d for _s, d, _l in sorted(affine, key=lambda a: -a[0])[:3]] + list(DEFAULT_IMPULSE_CATEG)
                lifts = {d: l for _s, d, l in affine}
                used = {c[1]['product'].id for c in cands}
                for categ in dict.fromkeys(pool):
                    options = sorted(
                        (q for q in info.values() if q['categ'] == categ and sellable(q) and q['price'] <= 4000
                         and q['product'].id != pid and q['base_fam'] != p['base_fam']
                         and q['product'].id not in used),
                        key=lambda q: -(CLASS_BOOST.get(q['cls'], 1.0) * (q['margin'] / 50.0) * (1 + math.log1p(q['s90']))))
                    if not options:
                        continue
                    q = options[0]
                    reason = (f"rubro afín ({categ}, lift {lifts[categ]:.1f})" if categ in lifts
                              else "impulso por defecto")
                    cands.append(('category', q, f"¿Le sumás {q['name']} por {_fmt(q['price'])}?", reason, 0.01))
                    used.add(q['product'].id)
                    if len(cands) >= 2:
                        break

            for kind, q, text, reason, score in cands[:3]:
                vals.append({
                    'trigger_product_id': pid, 'product_id': q['product'].id, 'kind': kind,
                    'text': text, 'reason': reason, 'score': score, 'manual': False,
                })
        return vals
