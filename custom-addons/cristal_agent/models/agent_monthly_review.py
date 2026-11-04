# -*- coding: utf-8 -*-
"""
Revisión mensual automática del mayorista — v1.59 (Fase 5, ítem 25 del plan).

El día 1 de cada mes arma la revisión del mes anterior y la publica en el canal interno:
ventas mayoristas, embudo por origen, etapas contra el mes anterior, motor de acciones
contra su grupo de control, salidas del camión, ángulos de pauta, costo de Claudio y
recomendaciones con reglas fijas (no opina: compara números).
"""
import json
import logging
from datetime import datetime, time, timedelta

from markupsafe import Markup, escape

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MESES = ['', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
         'septiembre', 'octubre', 'noviembre', 'diciembre']
REACHED = ('planned', 'done')


def _money(v):
    return f"${v:,.0f}".replace(',', '.')


def _pct(a, b):
    return (100.0 * a / b) if b else 0.0


class CristalAgentMonthlyReview(models.Model):
    _name = 'cristal.agent.monthly.review'
    _description = "Cristal Agent — Revisión mensual del mayorista"
    _order = 'month desc'
    _rec_name = 'name'

    name = fields.Char(string="Mes", required=True)
    month = fields.Date(string="Primer día del mes", required=True, index=True)
    body_html = fields.Html(string="Revisión", sanitize=False)
    snapshot = fields.Text(string="Datos (JSON)")
    recommendations = fields.Text(string="Recomendaciones")
    posted = fields.Boolean(string="Publicada en el canal")

    _sql_constraints = [('month_uniq', 'unique(month)', "Ya hay una revisión para ese mes.")]

    # ───────────────────────── Datos ─────────────────────────
    @api.model
    def _utc(self, d):
        """Medianoche Argentina (UTC-3) del día d, en UTC naive."""
        return datetime.combine(d, time.min) + timedelta(hours=3)

    @api.model
    def collect(self, month_start):
        ms = month_start.replace(day=1)
        me = (ms + timedelta(days=32)).replace(day=1)
        a, b = self._utc(ms), self._utc(me)
        Partner = self.env['res.partner'].sudo()
        SO = self.env['sale.order'].sudo()
        may = self.env['res.partner.category'].sudo().search([('name', '=', 'Mayorista')], limit=1)
        data = {'month': ms.isoformat()}

        # Ventas mayoristas confirmadas del mes
        dom = [('state', 'in', ('sale', 'done')), ('date_order', '>=', a), ('date_order', '<', b)]
        if may:
            dom.append(('partner_id.commercial_partner_id.category_id', 'in', may.ids))
        orders = SO.search(dom)
        amount = sum(orders.mapped('amount_untaxed'))
        buyers = len(set(orders.mapped('partner_id.commercial_partner_id').ids))
        config = self.env['cristal.agent.config'].sudo().get_active()
        bot_users = self.env.ref('base.user_root') | (config.bot_user_id if config else self.env['res.users'])
        data['sales'] = {'orders': len(orders), 'amount': amount, 'buyers': buyers,
                         'ticket': amount / len(orders) if orders else 0.0,
                         'by_claudio': len(orders.filtered(
                             lambda o: o.create_uid in bot_users or o.user_id in bot_users))}

        # Embudo del mes (mismo cálculo que el informe semanal)
        f = self.env['cristal.agent.weekly.report'].sudo()._funnel(a, b, ms, me)
        data['funnel'] = {k: f[k] for k in ('funnel_new_contacts', 'funnel_new_quoted',
                                            'funnel_new_buyers', 'funnel_first_buyers',
                                            'funnel_first_amount')}
        data['by_origin'] = f.get('by_origin') or {}
        data['stages'] = f.get('stages') or {}

        # Motor de acciones: cada acción contra su control
        NBA = self.env['cristal.agent.nba'].sudo()
        recs = NBA.search([('date', '>=', ms), ('date', '<', me)])
        labels = dict(NBA._fields['action_code'].selection)
        by_action = {}
        for n in recs:
            row = by_action.setdefault(n.action_code, {'label': labels.get(n.action_code, n.action_code),
                                                       'reached': 0, 'reached_conv': 0,
                                                       'holdout': 0, 'holdout_conv': 0, 'amount': 0.0})
            if n.state in REACHED:
                row['reached'] += 1
                row['reached_conv'] += 1 if n.converted else 0
                row['amount'] += n.converted_amount or 0.0
            elif n.state == 'holdout':
                row['holdout'] += 1
                row['holdout_conv'] += 1 if n.converted else 0
        reached = recs.filtered(lambda n: n.state in REACHED)
        hold = recs.filtered(lambda n: n.state == 'holdout')
        cap = int(getattr(config, 'lifecycle_daily_cap', 30) or 30) if config else 30
        per_day = {}
        for n in reached:
            per_day[n.date] = per_day.get(n.date, 0) + 1
        data['nba'] = {
            'reached': len(reached), 'reached_conv': len(reached.filtered('converted')),
            'holdout': len(hold), 'holdout_conv': len(hold.filtered('converted')),
            'amount': sum(reached.mapped('converted_amount')), 'by_action': by_action,
            'days_active': len(per_day), 'days_at_cap': sum(1 for v in per_day.values() if v >= cap),
            'cap': cap,
        }

        # Ruta del camión
        Dep = self.env['cristal.agent.route.departure'].sudo()
        deps = []
        for d in Dep.search([('date', '>=', ms), ('date', '<', me)], order='date'):
            ok = d.order_ids.filtered(lambda o: o.state in ('sale', 'done'))
            deps.append({'name': d.circuit_id.name, 'date': d.date.isoformat(), 'state': d.state,
                         'orders': len(ok), 'amount': sum(ok.mapped('amount_untaxed'))})
        data['route'] = deps

        # Pauta: ángulos con resultados cargados por la rutina semanal
        Creative = self.env['cristal.agent.creative'].sudo()
        crs = Creative.search([('create_date', '>=', a - timedelta(days=31)), ('create_date', '<', b)])
        angles = {}
        for c in crs:
            row = angles.setdefault(c.angle, {'pieces': 0, 'with_results': 0, 'spend': 0.0,
                                              'conversations': 0, 'orders': 0})
            row['pieces'] += 1
            if c.results_date:
                row['with_results'] += 1
                row['spend'] += c.spend or 0.0
                row['conversations'] += c.conversations or 0
                row['orders'] += c.orders or 0
        data['angles'] = angles
        data['organic'] = Creative.search_count([('format', '=', 'organico'),
                                                 ('planned_date', '>=', ms), ('planned_date', '<', me)])

        # Costo de Claudio
        Run = self.env['cristal.agent.run'].sudo()
        runs = Run.search([('create_date', '>=', a), ('create_date', '<', b)])
        days = (me - ms).days
        budget = float(getattr(config, 'daily_budget_usd', 0.0) or 0.0) * days if config else 0.0
        data['claudio'] = {'runs': len(runs), 'cost_usd': sum(runs.mapped('cost_usd')),
                           'budget_usd': budget}
        return data

    # ───────────────────────── Reglas ─────────────────────────
    @api.model
    def recommend(self, data, prev=None):
        rec = []
        for code, r in (data['nba'].get('by_action') or {}).items():
            if r['reached'] >= 30 and r['holdout'] >= 5:
                t, c = _pct(r['reached_conv'], r['reached']), _pct(r['holdout_conv'], r['holdout'])
                if t <= c:
                    rec.append(f"La acción «{r['label']}» no vende más que su control ({t:.0f} % contra "
                               f"{c:.0f} % sin contacto, {r['reached']} clientes): cambiar el mensaje o pausarla.")
        n = data['nba']
        if n['days_active'] and n['days_at_cap'] * 2 >= n['days_active']:
            rec.append(f"El motor llenó el cupo de {n['cap']} acciones en {n['days_at_cap']} de "
                       f"{n['days_active']} días: subir el cupo diario o priorizar mejor.")
        if prev:
            def risk(st):
                return sum(v for k, v in (st or {}).items()
                           if k in ('En riesgo', 'Dormido') or 'riesgo' in k.lower() or 'dormido' in k.lower())
            r0, r1 = risk(prev.get('stages')), risk(data.get('stages'))
            if r0 and r1 > r0 * 1.10:
                rec.append(f"Clientes en riesgo y dormidos crecieron de {r0} a {r1}: reforzar la "
                           "reactivación (visita de Alejandra u oferta de regreso).")
            s0, s1 = (prev.get('sales') or {}).get('amount', 0.0), data['sales']['amount']
            if s0 and s1 < s0 * 0.9:
                rec.append(f"Las ventas mayoristas bajaron de {_money(s0)} a {_money(s1)}: revisar "
                           "qué etapa del embudo cayó antes de subir la pauta.")
        for d in data.get('route') or []:
            if d['state'] == 'realizada' and d['orders'] < 3:
                rec.append(f"La salida {d['name']} del {d['date'][8:10]}/{d['date'][5:7]} tuvo "
                           f"{d['orders']} pedidos: revisar la pauta y el aviso de esa zona.")
        ranked = [(r['spend'] / r['conversations'], ang) for ang, r in (data.get('angles') or {}).items()
                  if r['with_results'] >= 2 and r['conversations']]
        if len(ranked) >= 2:
            ranked.sort()
            rec.append(f"Ángulo ganador del mes: {ranked[0][1]} ({_money(ranked[0][0])} por conversación); "
                       f"el peor: {ranked[-1][1]} ({_money(ranked[-1][0])}). Más piezas del ganador.")
        c = data['claudio']
        if c['budget_usd'] and c['cost_usd'] > 0.8 * c['budget_usd']:
            rec.append(f"Claudio gastó US$ {c['cost_usd']:.2f} de US$ {c['budget_usd']:.2f} del mes: "
                       "revisar qué conversaciones pasan a Sonnet.")
        f = data['funnel']
        if f['funnel_new_contacts'] >= 20 and _pct(f['funnel_new_quoted'], f['funnel_new_contacts']) < 25:
            rec.append(f"Solo {_pct(f['funnel_new_quoted'], f['funnel_new_contacts']):.0f} % de los "
                       "contactos nuevos llegó a cotización: revisar el primer mensaje de Claudio.")
        if not rec:
            rec.append("Sin alertas: los números están dentro de lo esperado.")
        return rec

    # ───────────────────────── Render ─────────────────────────
    @api.model
    def render(self, data, rec, prev=None):
        s, f, n, c = data['sales'], data['funnel'], data['nba'], data['claudio']
        ms = fields.Date.from_string(data['month'])
        P = Markup
        out = P("<p>📊 <b>Revisión mensual del mayorista · %s %s</b></p>") % (MESES[ms.month], ms.year)
        prev_amt = (prev or {}).get('sales', {}).get('amount')
        var = (P(" (mes anterior %s)") % _money(prev_amt)) if prev_amt else P('')
        out += P("<p><b>Ventas:</b> %s pedidos · %s sin IVA%s · %s negocios · ticket %s · "
                 "%s pedidos cargados por Claudio.</p>") % (
            s['orders'], _money(s['amount']), var, s['buyers'], _money(s['ticket']), s['by_claudio'])
        out += P("<p><b>Embudo:</b> %s contactos nuevos → %s cotizados (%s %%) → %s compraron · "
                 "%s primeras compras por %s.</p>") % (
            f['funnel_new_contacts'], f['funnel_new_quoted'],
            f"{_pct(f['funnel_new_quoted'], f['funnel_new_contacts']):.0f}",
            f['funnel_new_buyers'], f['funnel_first_buyers'], _money(f['funnel_first_amount']))
        if data.get('by_origin'):
            rows = sorted(data['by_origin'].items(), key=lambda kv: -kv[1][0])[:6]
            out += P("<p><b>Por origen:</b> %s.</p>") % P(' · ').join(
                P("%s %s/%s/%s") % (escape(k), v[0], v[1], v[2]) for k, v in rows)
        if data.get('stages'):
            prev_st = (prev or {}).get('stages') or {}
            out += P("<p><b>Etapas hoy:</b> %s.</p>") % P(' · ').join(
                P("%s %s%s") % (escape(k), v, (f" ({v - prev_st[k]:+d})" if k in prev_st else ''))
                for k, v in data['stages'].items())
        out += P("<p><b>Motor de acciones:</b> %s contactados, %s compraron (%s %%) · control %s, "
                 "%s compraron (%s %%) · %s atribuidos.</p>") % (
            n['reached'], n['reached_conv'], f"{_pct(n['reached_conv'], n['reached']):.0f}",
            n['holdout'], n['holdout_conv'], f"{_pct(n['holdout_conv'], n['holdout']):.0f}",
            _money(n['amount']))
        if data.get('route'):
            out += P("<p><b>Camión:</b> %s.</p>") % P(' · ').join(
                P("%s %s/%s: %s pedidos, %s") % (escape(d['name']), d['date'][8:10], d['date'][5:7],
                                                  d['orders'], _money(d['amount']))
                for d in data['route'])
        if data.get('angles'):
            out += P("<p><b>Pauta:</b> %s · %s posteos orgánicos programados.</p>") % (
                P(' · ').join(P("%s %s piezas") % (escape(k), v['pieces'])
                              for k, v in data['angles'].items()), data.get('organic', 0))
        out += P("<p><b>Claudio:</b> %s conversaciones atendidas · US$ %s.</p>") % (
            c['runs'], f"{c['cost_usd']:.2f}")
        out += P("<p><b>Recomendaciones:</b></p><ul>%s</ul>") % P('').join(
            P("<li>%s</li>") % r for r in rec)
        return out

    # ───────────────────────── Ejecución ─────────────────────────
    @api.model
    def build(self, month_start, post=True):
        ms = month_start.replace(day=1)
        prev_rec = self.search([('month', '<', ms)], order='month desc', limit=1)
        prev = json.loads(prev_rec.snapshot) if prev_rec and prev_rec.snapshot else None
        data = self.collect(ms)
        rec = self.recommend(data, prev)
        html = self.render(data, rec, prev)
        vals = {'name': f"{MESES[ms.month].capitalize()} {ms.year}", 'month': ms,
                'body_html': html, 'snapshot': json.dumps(data, default=str),
                'recommendations': '\n'.join(rec)}
        review = self.search([('month', '=', ms)], limit=1)
        if review:
            review.write(vals)
        else:
            review = self.create(vals)
        if post and not review.posted:
            config = self.env['cristal.agent.config'].sudo().get_active()
            if config and config.internal_channel_id:
                try:
                    config.internal_channel_id.sudo().with_context(from_cristal_agent=True).message_post(
                        body=html, message_type='comment', subtype_xmlid='mail.mt_comment')
                    review.posted = True
                except Exception as e:  # noqa: BLE001
                    _logger.warning("Revisión mensual al canal falló: %s", e)
        return review

    @api.model
    def cron_monthly_review(self):
        """Todos los días: si no existe la revisión del mes anterior, la arma y la publica.
        Así, si el día 1 falla, sale el día 2."""
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config or not config.monthly_review_enabled:
            return False
        today = fields.Date.context_today(config)
        prev_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        if self.search_count([('month', '=', prev_month), ('posted', '=', True)]):
            return True
        self.build(prev_month)
        return True
