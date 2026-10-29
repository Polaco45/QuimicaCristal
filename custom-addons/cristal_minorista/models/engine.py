# -*- coding: utf-8 -*-
import logging
import statistics
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

HISTORY_DAYS = 730
CF_PRICELIST = 'L.C 1'   # lista de consumidor final; cualquier otra es precio de negocio
DEFAULT_CYCLE = 35        # mediana de recompra de consumidor final (oct-2026)
MIN_CYCLE, MAX_CYCLE = 14, 120
MIN_GAP = 3               # compras con menos días de diferencia cuentan como una


def _median_gap(dates):
    """Mediana de días entre compras (fechas distintas, separadas al menos MIN_GAP)."""
    days = sorted(set(dates))
    merged = []
    for d in days:
        if not merged or (d - merged[-1]).days >= MIN_GAP:
            merged.append(d)
    gaps = [(b - a).days for a, b in zip(merged, merged[1:])]
    return int(statistics.median(gaps)) if gaps else None


class CristalMinoristaEngine(models.AbstractModel):
    _name = 'cristal.minorista.engine'
    _description = 'Minorista — recálculo de clientes, ciclos y segmentos'

    @api.model
    def _anonymous_partner_id(self):
        value = self.env['ir.config_parameter'].sudo().get_param('cristal_minorista.anonymous_partner_id')
        return int(value) if value and value.isdigit() else 0

    @api.model
    def _refresh_wholesale_buyers(self, since):
        """Marca a quien tiene pedidos confirmados con una lista que no es la de consumidor
        final (Lista Mayorista, L.E, etc.): esos clientes son negocios aunque no tengan CUIT."""
        cf_pricelist = self.env['product.pricelist'].sudo().search([('name', '=', CF_PRICELIST)], limit=1)
        orders = self.env['sale.order'].sudo().search([
            ('state', '=', 'sale'), ('date_order', '>=', since),
            ('pricelist_id', '!=', cf_pricelist.id)])
        buyers = orders.partner_id.commercial_partner_id
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        Partner.search([('cristal_wholesale_buyer', '=', True), ('id', 'not in', buyers.ids)]).write(
            {'cristal_wholesale_buyer': False})
        buyers.filtered(lambda p: not p.cristal_wholesale_buyer).write({'cristal_wholesale_buyer': True})
        return buyers

    @api.model
    def _purchases(self, since):
        """Compras de los últimos HISTORY_DAYS días: [(partner_comercial, fecha, monto, canal, origen, order)]."""
        anon = self._anonymous_partner_id()
        rows = []
        pos_orders = self.env['pos.order'].sudo().search_read(
            [('date_order', '>=', since), ('state', 'in', ('paid', 'done', 'invoiced')),
             ('partner_id', '!=', False), ('amount_total', '>', 0)],
            ['partner_id', 'cristal_customer_id', 'date_order', 'amount_total', 'cristal_origin'], load=False)
        for o in pos_orders:
            # Ticket anónimo de un cliente que dejó su WhatsApp en la caja
            if o['cristal_customer_id']:
                o['partner_id'] = o['cristal_customer_id']
        sale_orders =self.env['sale.order'].sudo().search_read(
            [('date_order', '>=', since), ('state', '=', 'sale'),
             ('partner_id', '!=', False), ('amount_total', '>', 0)],
            ['partner_id', 'date_order', 'amount_total', 'cristal_origin'], load=False)
        partner_ids = {o['partner_id'] for o in pos_orders + sale_orders}
        commercial = {p.id: p.commercial_partner_id.id
                      for p in self.env['res.partner'].sudo().browse(list(partner_ids))}
        for model, orders in (('pos.order', pos_orders), ('sale.order', sale_orders)):
            channel_default = 'local' if model == 'pos.order' else None
            for o in orders:
                if o['partner_id'] == anon:
                    continue
                origin = o['cristal_origin'] or channel_default or 'manual'
                channel = 'local' if model == 'pos.order' else ('web' if origin == 'web' else 'whatsapp' if origin == 'whatsapp_ia' else 'pedido')
                rows.append((commercial.get(o['partner_id'], o['partner_id']),
                             fields.Date.to_date(o['date_order']), o['amount_total'],
                             channel, origin, (model, o['id'])))
        return rows

    @api.model
    def _cron_refresh(self):
        today = fields.Date.context_today(self)
        since = fields.Datetime.now() - timedelta(days=HISTORY_DAYS)
        year_ago = today - timedelta(days=365)
        self._refresh_wholesale_buyers(since)
        rows = self._purchases(since)

        by_partner = defaultdict(list)
        for partner_id, date, amount, channel, origin, ref in rows:
            by_partner[partner_id].append((date, amount, channel, origin))

        # Umbral de "monto alto": percentil 80 de la facturación anual
        amounts = sorted(sum(a for d, a, c, o in purchases if d >= year_ago)
                         for purchases in by_partner.values())
        amounts = [a for a in amounts if a > 0]
        high_amount = amounts[int(len(amounts) * 0.8)] if amounts else 0

        Partner = self.env['res.partner'].sudo().with_context(tracking_disable=True)
        updated = set()
        for partner_id, purchases in by_partner.items():
            purchases.sort()
            dates = [p[0] for p in purchases]
            last = dates[-1]
            in_year = [p for p in purchases if p[0] >= year_ago]
            amount_365 = sum(p[1] for p in in_year)
            n_total = len(set(dates))
            n_365 = len({p[0] for p in in_year})
            gap = _median_gap(dates)
            cycle = min(max(gap or DEFAULT_CYCLE, MIN_CYCLE), MAX_CYCLE)
            recency = (today - last).days
            if recency <= 1.5 * cycle:
                if n_365 >= 6 and amount_365 >= high_amount:
                    segment = 'campeon'
                elif n_total <= 2:
                    segment = 'nuevo'
                else:
                    segment = 'leal'
            elif recency <= 3 * cycle:
                segment = 'en_riesgo'
            elif amount_365 >= high_amount and n_total >= 3:
                segment = 'no_perder'
            elif recency <= 6 * cycle:
                segment = 'dormido'
            else:
                segment = 'perdido'
            Partner.browse(partner_id).write({
                'cristal_first_purchase': dates[0],
                'cristal_last_purchase': last,
                'cristal_purchases_total': n_total,
                'cristal_purchases_365': n_365,
                'cristal_amount_365': amount_365,
                'cristal_avg_ticket': amount_365 / len(in_year) if in_year else 0.0,
                'cristal_cycle_days': cycle,
                'cristal_recency_days': recency,
                'cristal_channels': ', '.join(sorted({p[2] for p in purchases})),
                'cristal_first_origin': purchases[0][3],
                'cristal_segment': segment,
                'cristal_segment_date': today,
            })
            updated.add(partner_id)

        # Los que ya no tienen compras en la ventana
        stale = Partner.search([('cristal_segment', 'not in', (False, 'sin_compras')),
                                ('id', 'not in', list(updated))])
        stale.write({'cristal_segment': 'perdido', 'cristal_segment_date': today,
                     'cristal_purchases_365': 0, 'cristal_amount_365': 0.0})
        for partner in stale.filtered('cristal_last_purchase'):
            partner.cristal_recency_days = (today - partner.cristal_last_purchase).days

        self._refresh_duplicates()
        self._refresh_cycles(since, today)
        _logger.info("cristal_minorista: %s clientes recalculados, %s sin compras recientes",
                     len(updated), len(stale))

    @api.model
    def _refresh_duplicates(self):
        cr = self.env.cr
        cr.execute("""
            UPDATE res_partner p SET cristal_wa_dup_count = d.n
              FROM (SELECT cristal_wa_key, count(*) n FROM res_partner
                     WHERE active AND cristal_wa_key IS NOT NULL AND parent_id IS NULL
                     GROUP BY cristal_wa_key) d
             WHERE p.cristal_wa_key = d.cristal_wa_key AND p.parent_id IS NULL
               AND p.cristal_wa_dup_count IS DISTINCT FROM d.n
        """)
        cr.execute("""UPDATE res_partner SET cristal_wa_dup_count = 0
                       WHERE cristal_wa_key IS NULL AND cristal_wa_dup_count <> 0""")
        self.env['res.partner'].invalidate_model(['cristal_wa_dup_count'])

    @api.model
    def _refresh_cycles(self, since, today):
        families = self.env['cristal.cf.family'].sudo().search([])
        if not families:
            return
        products = self.env['product.product'].sudo().with_context(active_test=False).search(
            [('sale_ok', '=', True), ('type', '!=', 'combo')])
        family_of = {}
        counts = defaultdict(int)
        for product in products:
            name = (product.display_name or '').lower()
            for family in families:
                if any(p in name for p in family._patterns()):
                    family_of[product.id] = family.id
                    counts[family.id] += 1
                    break
        anon = self._anonymous_partner_id()
        events = defaultdict(lambda: defaultdict(float))   # (partner, family) -> {fecha: cantidad}
        line_specs = (
            ('pos.order.line', [('order_id.date_order', '>=', since),
                                ('order_id.state', 'in', ('paid', 'done', 'invoiced')),
                                ('order_id.partner_id', '!=', False), ('qty', '>', 0)],
             'qty', 'order_id'),
            ('sale.order.line', [('order_id.date_order', '>=', since), ('order_id.state', '=', 'sale'),
                                 ('product_uom_qty', '>', 0)],
             'product_uom_qty', 'order_id'),
        )
        for model, domain, qty_field, order_field in line_specs:
            domain = domain + [('product_id', 'in', list(family_of))]
            lines = self.env[model].sudo().search_read(domain, ['product_id', qty_field, order_field], load=False)
            orders = self.env[model.replace('.line', '')].sudo().browse(
                list({l[order_field] for l in lines}))
            info = {}
            for o in orders:
                # Ticket anónimo de un cliente que dejó su WhatsApp en la caja
                partner = o.partner_id
                if model == 'pos.order.line' and o.cristal_customer_id:
                    partner = o.cristal_customer_id
                info[o.id] = (partner.commercial_partner_id.id, fields.Date.to_date(o.date_order), partner.id)
            for line in lines:
                partner_id, date, raw_partner = info[line[order_field]]
                if raw_partner == anon:
                    continue
                events[(partner_id, family_of[line['product_id']])][date] += line[qty_field]

        personal = defaultdict(list)
        typical_qty = defaultdict(list)
        for (partner_id, family_id), by_date in events.items():
            gap = _median_gap(list(by_date))
            if gap:
                personal[family_id].append(gap)
            typical_qty[family_id].extend(by_date.values())

        population = {}
        for family in families:
            gaps = personal.get(family.id)
            population[family.id] = min(max(int(statistics.median(gaps)) if gaps else DEFAULT_CYCLE,
                                            MIN_CYCLE), MAX_CYCLE)
            family.write({'population_cycle_days': population[family.id],
                          'product_count': counts.get(family.id, 0)})

        Cycle = self.env['cristal.cf.cycle'].sudo()
        Cycle.search([]).unlink()
        vals_list = []
        for (partner_id, family_id), by_date in events.items():
            dates = sorted(by_date)
            last = dates[-1]
            gap = _median_gap(dates)
            cycle = min(max(gap, MIN_CYCLE), MAX_CYCLE) if gap else population[family_id]
            typical = statistics.median(typical_qty[family_id]) if typical_qty[family_id] else 1.0
            factor = min(max(by_date[last] / typical if typical else 1.0, 1.0), 3.0)
            vals_list.append({
                'partner_id': partner_id,
                'family_id': family_id,
                'purchases': len(dates),
                'last_date': last,
                'last_qty': by_date[last],
                'cycle_days': cycle,
                'cycle_source': 'personal' if gap else 'general',
                'next_due_date': last + timedelta(days=int(round(cycle * factor))),
            })
        Cycle.create(vals_list)
