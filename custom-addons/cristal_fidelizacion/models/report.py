# -*- coding: utf-8 -*-
"""Tablero semanal del minorista: los lunes, en el canal interno de Claudio.

Las 4 etapas en números (últimos 7 días contra los 7 anteriores): de dónde vinieron las
ventas, ticket y venta guiada, clientes anotados, mensajes automáticos y su efecto contra
el grupo de control.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta
from html import escape

from odoo import api, fields, models

from odoo.addons.cristal_minorista.models.origin import ORIGINS


def _money(value):
    return '$' + '{:,.0f}'.format(value or 0).replace(',', '.')


def _pct(part, total):
    return f"{round(100.0 * part / total)}%" if total else '—'


def _delta(now, before):
    if not before:
        return ''
    change = round(100.0 * (now - before) / before)
    return f" ({'+' if change >= 0 else ''}{change}% vs semana anterior)"


class CristalMinoristaReport(models.AbstractModel):
    _name = 'cristal.minorista.report'
    _description = 'Minorista — tablero semanal'

    @api.model
    def _sales(self, start, end):
        """Ventas a consumidor final: [(origen, monto, es_local)]."""
        anon = self.env['cristal.minorista.engine']._anonymous_partner_id()
        rows = []
        for o in self.env['pos.order'].sudo().search([
                ('date_order', '>=', start), ('date_order', '<', end),
                ('state', 'in', ('paid', 'done', 'invoiced')), ('amount_total', '>', 0)]):
            customer = o.cristal_customer_id or o.partner_id
            if customer and customer.id != anon and customer.cristal_customer_type != 'cf':
                continue
            rows.append((o.cristal_origin or 'local', o.amount_total, True))
        for o in self.env['sale.order'].sudo().search([
                ('date_order', '>=', start), ('date_order', '<', end), ('state', '=', 'sale'),
                ('partner_id.cristal_customer_type', '=', 'cf'), ('amount_total', '>', 0)]):
            rows.append((o.cristal_origin or 'manual', o.amount_total, False))
        return rows

    @api.model
    def build(self, date_to=None):
        """HTML del tablero de la semana que termina el día anterior a date_to."""
        today = date_to or fields.Date.context_today(self)
        end = datetime.combine(today, time.min)
        start = end - timedelta(days=7)
        prev = start - timedelta(days=7)
        now_rows, prev_rows = self._sales(start, end), self._sales(prev, start)
        labels = dict(ORIGINS)

        total = sum(r[1] for r in now_rows)
        total_prev = sum(r[1] for r in prev_rows)
        by_origin = defaultdict(lambda: [0, 0.0])
        for origin, amount, _local in now_rows:
            by_origin[origin][0] += 1
            by_origin[origin][1] += amount
        local = [r[1] for r in now_rows if r[2]]
        local_prev = [r[1] for r in prev_rows if r[2]]
        ticket = sum(local) / len(local) if local else 0
        ticket_prev = sum(local_prev) / len(local_prev) if local_prev else 0

        parts = [f"<p><b>📊 Minorista — semana del {start.strftime('%d/%m')} al "
                 f"{(end - timedelta(days=1)).strftime('%d/%m')}</b></p>"]

        # 1 · Captación
        Partner = self.env['res.partner'].sudo()
        optins = Partner.search_count([('cristal_mkt_optin_date', '>=', start), ('cristal_mkt_optin_date', '<', end)])
        optin_local = Partner.search_count([('cristal_mkt_optin_date', '>=', start), ('cristal_mkt_optin_date', '<', end),
                                            ('cristal_mkt_optin_source', '=', 'local')])
        allowed = Partner.search_count([('cristal_mkt_allowed', '=', True)])
        origin_txt = ', '.join(f"{escape(labels.get(k, k))} {v[0]} ({_money(v[1])})"
                               for k, v in sorted(by_origin.items(), key=lambda kv: -kv[1][1]))
        parts.append(
            f"<p><b>1 · Captación</b><br/>Ventas a consumidor final: {len(now_rows)} por "
            f"{_money(total)}{_delta(total, total_prev)}.<br/>Por origen: {origin_txt or '—'}.<br/>"
            f"Clientes anotados para avisos: {optins} esta semana ({optin_local} en la caja); "
            f"{allowed} en total.</p>")

        # 2 · Conversión (Claudio)
        quotes = self.env['sale.order'].sudo().search([
            ('create_date', '>=', start), ('create_date', '<', end), ('cristal_origin', '=', 'whatsapp_ia'),
            ('partner_id.cristal_customer_type', '=', 'cf')])
        won = quotes.filtered(lambda o: o.state == 'sale')
        parts.append(
            f"<p><b>2 · Conversión</b><br/>Cotizaciones de Claudio a consumidor final: {len(quotes)}; "
            f"confirmadas {len(won)} ({_pct(len(won), len(quotes))}) por {_money(sum(won.mapped('amount_total')))}.</p>")

        # 3 · Ticket
        vg_txt = ''
        if 'cristal.vg.event' in self.env:
            ev = self.env['cristal.vg.event'].sudo().search([('date', '>=', start), ('date', '<', end)])
            shown, acc = ev.filtered(lambda e: not e.accepted), ev.filtered('accepted')
            combos = acc.filtered(lambda e: e.kind == 'combo')
            vg_txt = (f"<br/>Venta guiada: {len(shown)} ofertas, {len(acc)} aceptadas "
                      f"({_pct(len(acc), len(shown))}), {_money(sum(acc.mapped('amount')))} sumados; "
                      f"combos armados: {len(combos)}.")
        parts.append(f"<p><b>3 · Ticket</b><br/>Ticket promedio en el local: {_money(ticket)}"
                     f"{_delta(ticket, ticket_prev)}.{vg_txt}</p>")

        # 4 · Fidelización
        Touch = self.env['cristal.fid.touch'].sudo()
        lines = []
        for flow in self.env['cristal.fid.flow'].sudo().search([]):
            t = Touch.search([('flow_id', '=', flow.id), ('date', '>=', start), ('date', '<', end)])
            sent, ctrl = t.filtered(lambda x: x.state == 'sent'), t.filtered(lambda x: x.state == 'holdout')
            if not (sent or ctrl):
                continue
            replied = sent.filtered('reply')
            conv = sent.filtered('converted')
            lines.append(
                f"{escape(flow.name)}: {len(sent)} enviados, {len(replied)} respondieron, "
                f"{len(conv)} compraron ({_pct(len(conv), len(sent))} vs {_pct(len(ctrl.filtered('converted')), len(ctrl))} "
                f"sin mensaje), {_money(sum(conv.mapped('converted_amount')))}")
        errors = Touch.search_count([('state', '=', 'error'), ('date', '>=', start), ('date', '<', end)])
        reviews = Partner.search_count([('cristal_review_asked_date', '>=', start), ('cristal_review_asked_date', '<', end)])
        segs = dict(Partner._fields['cristal_segment'].selection)
        counts = Partner.read_group([('cristal_customer_type', '=', 'cf'), ('cristal_segment', '!=', False)],
                                    ['cristal_segment'], ['cristal_segment'])
        seg_txt = ', '.join(f"{segs.get(c['cristal_segment'])} {c['cristal_segment_count']}" for c in counts)
        parts.append(
            "<p><b>4 · Fidelización</b><br/>" + ('<br/>'.join(lines) or 'Sin mensajes enviados esta semana.') +
            f"<br/>Pedidos de reseña en Google: {reviews}." + (f" ⚠️ Errores de envío: {errors}." if errors else '') +
            f"<br/>Clientes por segmento: {seg_txt or '—'}.</p>")
        return ''.join(parts)

    @api.model
    def _cron_weekly(self):
        config = self.env['cristal.agent.config'].sudo().get_active()
        channel = config.internal_channel_id if config else False
        if channel:
            channel.sudo().with_context(from_cristal_agent=True).message_post(
                body=self.build(), message_type='comment', subtype_xmlid='mail.mt_comment')
