# -*- coding: utf-8 -*-
"""
v1.43 — Informe semanal, números que WhatsApp rechaza y recordatorio de recompra.

Joaco (27/10/2026): "hacé todas esas mejoras". Lo que se automatiza acá:

1. Informe semanal (lunes 9 h): respuestas, costo, costo por respuesta y POR PEDIDO
   VENDIDO, cuántas pasaron al modelo avanzado y por qué, cotizaciones, pedidos
   confirmados, pases a Joaco, controles que frenaron mensajes, "No contactar" nuevos y
   una muestra de 20 conversaciones de Haiku para revisar a mano. Queda guardado (tablero)
   y se publica en el canal interno.
2. Números que WhatsApp rechaza (diario): si Meta dice que el cliente no quiere
   mensajes de marketing (131050) o que el número no tiene WhatsApp (131026 dos veces),
   el contacto pasa a "No contactar". Seguir mandándoles gasta y ensucia el número.
3. Recompra (diario): a quien compra seguido y ya pasó su intervalo habitual sin
   pedir, se le agenda un seguimiento para Claudio (máx. 15 por día).
"""
import logging
import random
import re
from collections import Counter
from datetime import datetime, timedelta
from statistics import median

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

REORDER_MAX_PER_DAY = 15
REORDER_MIN_ORDERS = 3
REVIEW_SAMPLE_SIZE = 20


class CristalAgentWeeklyReport(models.Model):
    _name = 'cristal.agent.weekly.report'
    _description = "Cristal Agent — Informe semanal"
    _order = 'week_start desc'
    _rec_name = 'week_start'

    week_start = fields.Date(string="Semana desde", required=True)
    week_end = fields.Date(string="Hasta (excl.)", required=True)
    replies = fields.Integer(string="Respuestas a clientes")
    runs_total = fields.Integer(string="Corridas totales")
    cost_usd = fields.Float(string="Costo USD", digits=(10, 2))
    cost_per_reply = fields.Float(string="Costo por respuesta", digits=(10, 4))
    strong_runs = fields.Integer(string="Con modelo avanzado")
    strong_pct = fields.Float(string="% modelo avanzado", digits=(5, 1))
    quotes = fields.Integer(string="Cotizaciones de Claudio")
    orders_confirmed = fields.Integer(string="Pedidos confirmados")
    sold_amount = fields.Float(string="Vendido (sin IVA)", digits=(12, 0))
    cost_per_order = fields.Float(string="Costo por pedido vendido", digits=(10, 2))
    escalations = fields.Integer(string="Pases a Joaco")
    guard_blocks = fields.Integer(string="Mensajes frenados por controles")
    opt_outs = fields.Integer(string="Nuevos 'No contactar'")
    errors = fields.Integer(string="Corridas con error")
    body = fields.Html(string="Informe", sanitize=False)

    # ───────────────────────── Informe semanal ─────────────────────────
    @api.model
    def cron_weekly_report(self):
        """Lunes: informe de la semana anterior (lunes a domingo, hora Argentina)."""
        from ..services.helpers import now_ar
        today = now_ar(self.env).date()
        start = today - timedelta(days=today.weekday() + 7)
        rep = self.build_report(start, start + timedelta(days=7))
        rep._post_to_internal_channel()
        return rep

    @api.model
    def _utc_bounds(self, start, end):
        import pytz
        from ..services.helpers import tz_ar
        tz = tz_ar(self.env)

        def to_utc(d):
            return tz.localize(datetime.combine(d, datetime.min.time())).astimezone(
                pytz.utc).replace(tzinfo=None)
        return to_utc(start), to_utc(end)

    @api.model
    def build_report(self, start, end):
        """Calcula y guarda (o actualiza) el informe de [start, end)."""
        import json
        a, b = self._utc_bounds(start, end)
        Run = self.env['cristal.agent.run'].sudo()
        runs = Run.search([('create_date', '>=', a), ('create_date', '<', b)])
        replies = runs.filtered(lambda r: r.trigger == 'whatsapp_message' and r.state == 'done')
        config = self.env['cristal.agent.config'].sudo().get_active()
        strong = (config.anthropic_model_complex or '').strip() if config else ''
        strong_runs = runs.filtered(lambda r: strong and r.model_used == strong)
        reasons = Counter(
            (r.model_reason or '').split(' → ')[-1].replace('avanzado (', '').rstrip(')')
            or 'sin dato' for r in strong_runs)

        quote_ids, escal, guards = set(), 0, Counter()
        for r in runs:
            try:
                log = json.loads(r.tool_calls_log or '[]') or []
            except Exception:
                continue
            for t in log if isinstance(log, list) else []:
                out = t.get('output') or {}
                name = t.get('tool_name')
                if name == 'create_sale_order' and isinstance(out, dict) and out.get('order_id'):
                    quote_ids.add(out['order_id'])
                elif name == 'escalate_to_joaco':
                    escal += 1
                elif name == 'send_whatsapp' and isinstance(out, dict) and out.get('guard'):
                    guards[out['guard']] += 1

        # Pedidos de Claudio (cotizados en los últimos 45 días) confirmados en la semana.
        recent_quotes = set(quote_ids)
        older = Run.search([('create_date', '>=', a - timedelta(days=45)), ('create_date', '<', a),
                            ('tool_calls_log', 'ilike', 'create_sale_order')])
        for r in older:
            for m in re.finditer(r'"order_id":\s*(\d+)', r.tool_calls_log or ''):
                recent_quotes.add(int(m.group(1)))
        orders = self.env['sale.order'].sudo().search([
            ('id', 'in', list(recent_quotes)), ('state', 'in', ('sale', 'done')),
            ('date_order', '>=', a), ('date_order', '<', b)])
        cost = sum(runs.mapped('cost_usd'))
        n_orders = len(orders)
        opt_outs = self.env['res.partner'].sudo().search_count([
            ('agent_opt_out', '=', True), ('agent_opt_out_date', '>=', a),
            ('agent_opt_out_date', '<', b)])

        # Muestra para revisar a mano: 20 respuestas del modelo base, al azar.
        base_replies = replies.filtered(lambda r: not strong or r.model_used != strong)
        sample = Run.browse(random.sample(base_replies.ids, min(REVIEW_SAMPLE_SIZE,
                                                                 len(base_replies))))
        sample.write({'review_sample': True})

        vals = {
            'week_start': start, 'week_end': end,
            'replies': len(replies), 'runs_total': len(runs), 'cost_usd': cost,
            'cost_per_reply': cost / len(replies) if replies else 0.0,
            'strong_runs': len(strong_runs),
            'strong_pct': 100.0 * len(strong_runs) / len(runs) if runs else 0.0,
            'quotes': len(quote_ids), 'orders_confirmed': n_orders,
            'sold_amount': sum(orders.mapped('amount_untaxed')),
            'cost_per_order': cost / n_orders if n_orders else 0.0,
            'escalations': escal, 'guard_blocks': sum(guards.values()),
            'opt_outs': opt_outs,
            'errors': len(runs.filtered(lambda r: r.state == 'error')),
        }
        vals['body'] = self._render(vals, reasons, guards, sample)
        rep = self.search([('week_start', '=', start)], limit=1)
        if rep:
            rep.write(vals)
        else:
            rep = self.create(vals)
        return rep

    @api.model
    def _render(self, v, reasons, guards, sample):
        def money(x, d=0):
            return ('US$ ' if d else '$') + f"{x:,.{d}f}".replace(',', 'X').replace(
                '.', ',').replace('X', '.')
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        rs = ', '.join(f"{k} ({n})" for k, n in reasons.most_common(5)) or '—'
        gs = ', '.join(f"{k} ({n})" for k, n in guards.most_common(6)) or 'ninguno'
        links = ''.join(
            f'<li><a href="{base}/web#model=cristal.agent.run&amp;id={r.id}&amp;view_type=form">'
            f'{(r.partner_id.name or "sin nombre")}</a> — {money(r.cost_usd, 4)}</li>'
            for r in sample)
        return (
            f"<p><b>📊 Claudio — semana del {v['week_start']:%d/%m} al "
            f"{(v['week_end'] - timedelta(days=1)):%d/%m}</b></p><ul>"
            f"<li>Respuestas a clientes: <b>{v['replies']}</b> · costo total "
            f"<b>{money(v['cost_usd'], 2)}</b> · por respuesta {money(v['cost_per_reply'], 4)}</li>"
            f"<li>Pedidos de Claudio confirmados: <b>{v['orders_confirmed']}</b> "
            f"({money(v['sold_amount'])} sin IVA) · <b>costo por pedido vendido "
            f"{money(v['cost_per_order'], 2)}</b> · cotizaciones nuevas: {v['quotes']}</li>"
            f"<li>Con el modelo avanzado: {v['strong_runs']} ({v['strong_pct']:.0f}%) — "
            f"motivos: {rs}</li>"
            f"<li>Pases a Joaco: {v['escalations']} · mensajes frenados por controles: "
            f"{v['guard_blocks']} ({gs}) · nuevos 'No contactar': {v['opt_outs']} · "
            f"corridas con error: {v['errors']}</li></ul>"
            f"<p><b>Para revisar</b> ({len(sample)} conversaciones de Haiku al azar; "
            f"marcá Bien / Con error en cada una, menú Claudio → Revisión semanal):</p>"
            f"<ul>{links or '<li>—</li>'}</ul>")

    def _post_to_internal_channel(self):
        config = self.env['cristal.agent.config'].sudo().get_active()
        channel = config.internal_channel_id if config else False
        for rep in self:
            if channel and rep.body:
                channel.sudo().with_context(from_cristal_agent=True).message_post(
                    body=rep.body, message_type='comment', subtype_xmlid='mail.mt_comment')

    # ─────────────────── Números que WhatsApp rechaza ───────────────────
    @api.model
    def cron_wa_failures(self, days=2):
        """Pasa a 'No contactar' a quien WhatsApp no deja escribirle (solo plantillas
        de la cuenta de Claudio). Devuelve [(partner, motivo)]."""
        WA = self.env['whatsapp.message'].sudo()
        since = fields.Datetime.now() - timedelta(days=days)
        config = self.env['cristal.agent.config'].sudo().get_active()
        accounts = self.env['whatsapp.template'].sudo().search(
            [('template_name', '=', 'hola_mayorista_crm')]).mapped('wa_account_id')
        dom = [('message_type', '=', 'outbound'), ('wa_template_id', '!=', False),
               ('state', 'in', ('error', 'bounced')), ('create_date', '>=', since)]
        if accounts:
            dom.append(('wa_account_id', 'in', accounts.ids))
        fails = WA.search(dom)
        marked = []
        by_digits = {}
        for m in fails:
            digits = re.sub(r'\D', '', m.mobile_number or '')[-8:]
            if len(digits) == 8:
                by_digits.setdefault(digits, WA)
                by_digits[digits] |= m
        Partner = self.env['res.partner'].sudo()
        for digits, msgs in by_digits.items():
            reasons = ' '.join((x.failure_reason or '') for x in msgs)
            # ¿Volvió a escribir después del último rechazo? Entonces el número anda.
            last = max(msgs.mapped('create_date'))
            if WA.search_count([('message_type', '=', 'inbound'),
                                ('mobile_number', 'ilike', digits),
                                ('create_date', '>', last)]):
                continue
            reason = None
            if '131050' in reasons:
                reason = "WhatsApp: el cliente bloqueó los mensajes de marketing (131050)"
            else:
                undeliverable = WA.search([
                    ('message_type', '=', 'outbound'), ('mobile_number', 'ilike', digits),
                    ('failure_reason', 'ilike', '131026'),
                    ('create_date', '>=', fields.Datetime.now() - timedelta(days=120))])
                if len({d.date() for d in undeliverable.mapped('create_date')}) >= 2:
                    reason = "WhatsApp: número sin WhatsApp o no entregable (131026, 2 veces)"
            if not reason:
                continue
            partners = Partner.search(['|', ('mobile', 'ilike', digits),
                                       ('phone', 'ilike', digits),
                                       ('agent_opt_out', '=', False)])
            if config and config.owner_whatsapp_partner_id:
                partners -= config.owner_whatsapp_partner_id
            for p in partners:
                p.set_agent_opt_out(reason)
                marked.append((p, reason))
        if marked:
            _logger.info("📵 %s contactos a 'No contactar' por rechazos de WhatsApp", len(marked))
        return marked

    # ───────────────────────────── Recompra ─────────────────────────────
    @api.model
    def reorder_candidates(self, today=None, limit=REORDER_MAX_PER_DAY):
        """[(partner, intervalo_días, días_desde_última, productos)] de mayoristas que
        compran seguido y ya pasaron su intervalo habitual sin pedir."""
        today = today or fields.Date.context_today(self)
        SO = self.env['sale.order'].sudo()
        may = self.env['res.partner.category'].sudo().search([('name', '=', 'Mayorista')],
                                                             limit=1)
        if not may:
            return []
        groups = SO.read_group([('state', 'in', ('sale', 'done')),
                                ('date_order', '>=', today - timedelta(days=365)),
                                ('partner_id.category_id', 'in', may.ids)],
                               ['partner_id'], ['partner_id'], lazy=False)
        Memory = self.env['cristal.agent.memory'].sudo()
        out = []
        for g in groups:
            if g['__count'] < REORDER_MIN_ORDERS or not g['partner_id']:
                continue
            partner = self.env['res.partner'].sudo().browse(g['partner_id'][0])
            if partner.agent_opt_out or not (partner.mobile or partner.phone):
                continue
            orders = SO.search([('partner_id', '=', partner.id), ('state', 'in', ('sale', 'done'))],
                               order='date_order asc')
            dates = sorted({o.date_order.date() for o in orders if o.date_order})
            if len(dates) < REORDER_MIN_ORDERS:
                continue
            gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
            if not gaps:
                continue
            interval = max(7, int(median(gaps)))
            since = (today - dates[-1]).days
            if since < interval or since > interval * 3:
                continue  # todavía no le toca, o ya es un cliente perdido (otra cadencia)
            if SO.search_count([('partner_id', '=', partner.id), ('state', 'in', ('draft', 'sent')),
                                ('create_date', '>=', today - timedelta(days=14))]):
                continue
            last_rem = partner.agent_reorder_reminder_date
            if last_rem and (today - last_rem).days < interval:
                continue
            mem = Memory.search([('partner_id', '=', partner.id)], limit=1)
            if mem and mem.is_takeover_active():
                continue
            top = Counter()
            for o in orders[-3:]:
                for l in o.order_line.filtered(lambda x: not x.display_type and x.product_id):
                    top[l.product_id.name] += l.product_uom_qty
            products = ', '.join(n for n, _q in top.most_common(5))
            out.append((partner, interval, since, products))
        out.sort(key=lambda x: x[2] / x[1], reverse=True)
        return out[:limit]

    @api.model
    def cron_reorder_reminders(self):
        """Agenda para Claudio un seguimiento de recompra (lo ejecuta el cron de
        actividades, con ventana/plantilla, horario y 'No contactar' ya resueltos)."""
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config or not config.enabled or not config.bot_user_id:
            return []
        today = fields.Date.context_today(self)
        done = []
        for partner, interval, since, products in self.reorder_candidates(today):
            lead = self.env['crm.lead'].sudo().search([
                ('partner_id', '=', partner.id), ('active', '=', True)],
                order='create_date desc', limit=1)
            target = lead or partner
            target.activity_schedule(
                'mail.mail_activity_data_todo', date_deadline=today,
                summary=f"Recompra: suele comprar cada ~{interval} días (última hace {since})",
                note=(f"Cliente que compra seguido y ya pasó su intervalo habitual sin pedir. "
                      f"Productos que suele llevar: {products or '—'}. Escribile corto "
                      f"ofreciéndole reponer esos productos (con la promo vigente si aplica)."),
                user_id=config.bot_user_id.id)
            partner.agent_reorder_reminder_date = today
            done.append(partner)
        if done:
            _logger.info("🔁 Recompra: %s seguimientos agendados", len(done))
        return done
