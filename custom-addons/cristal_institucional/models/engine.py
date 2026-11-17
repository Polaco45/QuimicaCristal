import logging
from datetime import timedelta
from statistics import median

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Valores por defecto; se cambian en Ajustes → Técnico → Parámetros del sistema
# con la clave "cristal_institucional.<nombre>".
DEFAULTS = {
    'kit_followup_days': 5,            # a los cuántos días del kit se llama
    'first_purchase_deadline_days': 30,  # fecha límite para la primera compra, desde el kit
    'reorder_deadline_days': 30,       # fecha límite para el segundo pedido, desde la primera compra
    'reorder_call_days': 21,           # cuándo se llama para la reposición
    'default_cycle_days': 30,          # ritmo de compra si todavía no hay historial
    'risk_factor_pct': 150,            # en riesgo: pasó 1,5 veces su ritmo
    'dormant_cycles': 3,               # dormido: pasó 3 veces su ritmo...
    'dormant_min_days': 90,            # ...o al menos 90 días
}
KIT_TAG_PARAM = 'cristal_institucional.kit_tag'
KIT_TAG_DEFAULT = 'Regalo captación'


class CristalInstEngine(models.AbstractModel):
    _name = 'cristal.inst.engine'
    _description = 'Institucional: motor de etapas, alertas y próximo paso'

    # ------------------------------------------------------------------ config
    @api.model
    def _params(self):
        icp = self.env['ir.config_parameter'].sudo()
        out = {}
        for key, default in DEFAULTS.items():
            try:
                out[key] = int(icp.get_param('cristal_institucional.%s' % key, default))
            except (TypeError, ValueError):
                out[key] = default
        out['kit_tag'] = icp.get_param(KIT_TAG_PARAM, KIT_TAG_DEFAULT)
        return out

    # ------------------------------------------------------------------- datos
    @api.model
    def _gather(self, partners, params):
        """Devuelve por empresa: compras reales (fecha, monto, margen) y el kit."""
        data = {p.id: {'orders': [], 'kit_order': False, 'kit_date': False, 'fams': set()} for p in partners}
        if not partners:
            return data
        since = fields.Date.context_today(self) - timedelta(days=365)
        recent = {}
        SaleOrder = self.env['sale.order'].sudo()
        orders = SaleOrder.search([
            ('partner_id', 'child_of', partners.ids),
            ('state', '!=', 'cancel'),
        ])
        has_tags = 'tag_ids' in SaleOrder._fields
        kit_tag = (params['kit_tag'] or '').strip().lower()
        for order in orders:
            pid = order.partner_id.commercial_partner_id.id
            if pid not in data:
                continue
            is_kit = bool(has_tags and kit_tag and any(
                (t.name or '').strip().lower() == kit_tag for t in order.tag_ids))
            if is_kit:
                delivered = False
                if order.state in ('sale', 'done'):
                    done = order.picking_ids.filtered(lambda pk: pk.state == 'done' and pk.date_done)
                    if done:
                        delivered = max(done.mapped('date_done')).date()
                current = data[pid]
                if not current['kit_order'] or (delivered and not current['kit_date']):
                    current['kit_order'] = order.id
                    current['kit_date'] = delivered
                continue
            if order.state in ('sale', 'done') and order.amount_untaxed > 0:
                data[pid]['orders'].append(
                    (order.date_order.date(), order.amount_untaxed, order.margin or 0.0))
                if order.date_order.date() >= since:
                    recent[order.id] = pid
        # Qué familias de productos compró cada empresa en los últimos 12 meses
        if recent:
            lines = self.env['sale.order.line'].sudo().search([
                ('order_id', 'in', list(recent)),
                ('display_type', '=', False),
                ('price_subtotal', '>', 0),
                ('product_id', '!=', False),
            ])
            for line in lines:
                data[recent[line.order_id.id]]['fams'].add(self._family(line.product_id.categ_id))
        if 'pos.order' in self.env:
            PosOrder = self.env['pos.order'].sudo()
            pos_orders = PosOrder.search([
                ('partner_id', 'child_of', partners.ids),
                ('state', 'in', ('paid', 'done', 'invoiced')),
                ('amount_total', '>', 0),
            ])
            for order in pos_orders:
                pid = order.partner_id.commercial_partner_id.id
                if pid in data:
                    untaxed = (order.amount_total or 0.0) - (order.amount_tax or 0.0)
                    margin = order.margin if 'margin' in PosOrder._fields else 0.0
                    data[pid]['orders'].append((order.date_order.date(), untaxed, margin or 0.0))
        return data

    @api.model
    def _family(self, categ):
        """Familia = los dos primeros niveles de la categoría (ej. 'Fabricación / Detergente')."""
        parts = [p.strip() for p in (categ.complete_name or '').split('/') if p.strip()]
        return ' / '.join(parts[:2]) if parts else ''

    @api.model
    def _reference_families(self):
        """Familias de fabricación propia: son las que más margen dejan y las que conviene sumar."""
        Categ = self.env['product.category'].sudo()
        roots = Categ.search([('parent_id', '=', False), ('name', '=ilike', 'Fabricaci%')])
        if not roots:
            roots = Categ.search([('name', '=ilike', 'Fabricaci%')], limit=1)
        children = Categ.search([('parent_id', 'in', roots.ids)]) if roots else Categ
        return sorted({self._family(c) for c in children if self._family(c)})

    # ------------------------------------------------------------ clasificación
    @api.model
    def _classify(self, partner, info, params, today):
        orders = sorted(info['orders'])
        dates = sorted({d for d, _a, _m in orders})
        count = len(dates)
        vals = {
            'inst_order_count': count,
            'inst_first_order': dates[0] if dates else False,
            'inst_last_order': dates[-1] if dates else False,
            'inst_kit_order_id': info['kit_order'] or False,
        }
        kit_date = partner.inst_kit_date or info['kit_date'] or False
        if info['kit_date'] and not partner.inst_kit_date:
            vals['inst_kit_date'] = info['kit_date']
        contactado = partner.inst_contactado
        if not contactado and (partner.inst_decisor_id or kit_date or info['kit_order']):
            contactado = today
            vals['inst_contactado'] = today

        # Indicadores de los últimos 12 meses
        since = today - timedelta(days=365)
        amount = sum(a for d, a, _m in orders if d >= since)
        margin = sum(m for d, _a, m in orders if d >= since)
        months = 12.0
        if dates and dates[0] > since:
            months = max(1.0, (today - dates[0]).days / 30.0)
        vals.update({
            'inst_amount_12m': amount,
            'inst_margin_12m': margin,
            'inst_margin_month': margin / months if margin else 0.0,
            'inst_margin_pct': (100.0 * margin / amount) if amount else 0.0,
        })

        # Ritmo de compra propio de la empresa
        gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        cycle = max(7, int(median(gaps))) if gaps else params['default_cycle_days']
        days_since = (today - dates[-1]).days if dates else 0
        vals['inst_cycle_days'] = cycle if dates else 0

        # Qué compra y qué le falta sumar (fabricación propia)
        fams = info.get('fams') or set()
        short = lambda fam: fam.split(' / ')[-1]
        gaps = [short(f) for f in params.get('ref_fams', []) if f not in fams] if count else []
        vals['inst_buys'] = ', '.join(sorted(short(f) for f in fams))[:250] or False
        vals['inst_gaps'] = ', '.join(gaps)[:250] or False

        alert = 'ok'
        step, step_date, deadline, expected, late = False, False, False, False, 0

        if partner.inst_discarded:
            stage = 'descartado'
            reason = partner.inst_discard_reason or 'Descartado'
            alert = False
        elif count >= 2:
            stage = 'recurrente'
            expected = dates[-1] + timedelta(days=cycle)
            late = max(0, (today - expected).days)
            reason = '%s compras; compra cada %s días' % (count, cycle)
            if days_since > max(params['dormant_cycles'] * cycle, params['dormant_min_days']):
                alert = 'dormido'
                step = 'Llamar: lleva %s días sin comprar. Saber por qué dejó de comprar' % days_since
                step_date = today
            elif days_since > cycle * params['risk_factor_pct'] / 100.0:
                alert = 'riesgo'
                step = 'Llamar: se atrasó %s días respecto de su ritmo de compra' % late
                step_date = today
            else:
                step = 'Reposición esperada: confirmar el pedido'
                if gaps:
                    step += ' y ofrecerle %s' % ' o '.join(gaps[:2]).lower()
                step_date = expected
        elif count == 1:
            stage = 'pedido_formal'
            reason = 'Una compra, el %s' % dates[-1].strftime('%d/%m/%Y')
            step = 'Llamada de reposición: cómo les fue y armar el mismo pedido'
            step_date = dates[-1] + timedelta(days=params['reorder_call_days'])
            deadline = dates[-1] + timedelta(days=params['reorder_deadline_days'])
            expected = deadline
            if days_since > params['dormant_min_days']:
                alert = 'dormido'
                step = 'Llamar: compró una vez hace %s días y no volvió. Saber por qué' % days_since
                step_date = today
                deadline = False
        elif kit_date:
            stage = 'primera_compra'
            reason = 'Kit entregado el %s, todavía no compró' % kit_date.strftime('%d/%m/%Y')
            step = 'Llamar: cómo les fue con el kit y pasar la propuesta de primera compra'
            step_date = kit_date + timedelta(days=params['kit_followup_days'])
            deadline = kit_date + timedelta(days=params['first_purchase_deadline_days'])
        elif contactado:
            stage = 'captacion'
            if info['kit_order']:
                reason = 'Kit cargado, falta entregarlo'
                step = 'Entregar el kit de prueba'
            elif partner.inst_last_result == 'kit':
                reason = 'Aceptó el kit, falta cargarlo'
                step = 'Cargar el kit de prueba y entregarlo'
            elif partner.inst_ficha_falta:
                reason = 'Falta en la ficha: %s' % partner.inst_ficha_falta
                step = 'Completar la ficha y ofrecer el kit de prueba'
            else:
                reason = 'Ficha completa, falta cargar el kit'
                step = 'Cargar y entregar el kit de prueba'
            step_date = today
        else:
            stage = 'prospecto'
            reason = 'Todavía no hablamos con nadie de la empresa'
            step = 'Llamar: conseguir a quien decide las compras'
            step_date = today

        # Posponer: corre el paso y la fecha límite
        postponed = partner.inst_postponed_until
        if postponed and stage != 'descartado':
            if postponed > today:
                step_date = postponed
                if deadline and deadline < postponed:
                    deadline = postponed
                if alert in ('riesgo', 'dormido'):
                    alert = 'ok'
            else:
                vals['inst_postponed_until'] = False
        if stage != 'descartado' and alert == 'ok' and deadline and deadline < today:
            alert = 'vence'
            step = 'Fecha límite vencida: %s. Posponer con nueva fecha o descartar' % (step or '')
            step_date = today
        if stage == 'descartado':
            step, step_date, deadline = False, False, False

        # Intentos sin respuesta: al tercero se cambia de canal
        attempts = partner.inst_attempts
        if step and attempts and stage != 'descartado':
            if attempts >= 3:
                step = 'No atiende hace %s intentos: escribirle por WhatsApp o pasar por el local' % attempts
            else:
                step = '%s (intento %s)' % (step, attempts + 1)

        # Prioridad para ordenar "Mi día": primero lo que se puede perder y lo que más margen deja
        weights = {
            ('recurrente', 'riesgo'): 9, ('recurrente', 'dormido'): 6, ('recurrente', 'ok'): 2,
            ('primera_compra', 'vence'): 8, ('primera_compra', 'ok'): 7,
            ('pedido_formal', 'vence'): 8, ('pedido_formal', 'ok'): 7, ('pedido_formal', 'dormido'): 5,
            ('captacion', 'ok'): 4, ('prospecto', 'ok'): 3,
        }
        weight = weights.get((stage, alert), 0)
        if stage == 'captacion' and info['kit_order']:
            weight = 6
        margin_points = min(999.0, (vals.get('inst_margin_12m') or 0.0) / 10000.0)
        vals['inst_priority'] = round(weight * 1000 + margin_points, 2) if weight else 0.0

        vals.update({
            'inst_stage': stage,
            'inst_reason': reason,
            'inst_alert': alert,
            'inst_next_step': step,
            'inst_next_step_date': step_date,
            'inst_deadline': deadline,
            'inst_next_expected': expected,
            'inst_days_late': late,
        })
        if stage != partner.inst_stage:
            vals['inst_stage_date'] = today
        return vals

    # ---------------------------------------------------------------- cálculo
    @api.model
    def recompute(self, partners=None):
        Partner = self.env['res.partner'].sudo()
        if partners is None:
            partners = Partner.search([('inst_is', '=', True)])
        else:
            partners = partners.sudo().filtered('inst_is')
        if not partners:
            return 0
        params = self._params()
        params['ref_fams'] = self._reference_families()
        StageLog = self.env['cristal.inst.stage.log'].sudo()
        today = fields.Date.context_today(self)
        now = fields.Datetime.now()
        data = self._gather(partners, params)
        changed = 0
        for partner in partners.with_context(tracking_disable=True, inst_engine=True):
            vals = self._classify(partner, data[partner.id], params, today)
            diff = {}
            for key, value in vals.items():
                current = partner[key]
                if partner._fields[key].type == 'many2one':
                    current = current.id
                if (current or False) != (value or False):
                    diff[key] = value
            if diff:
                changed += 1
                diff['inst_computed_at'] = now
                if 'inst_stage' in diff:
                    previous_date = partner.inst_stage_date
                    StageLog.create({
                        'partner_id': partner.id,
                        'date': today,
                        'stage_from': partner.inst_stage or False,
                        'stage_to': diff['inst_stage'],
                        'days_in_previous': (today - previous_date).days if previous_date else 0,
                    })
                partner.write(diff)
        _logger.info('Institucional: %s empresas evaluadas, %s con cambios', len(partners), changed)
        return changed

    @api.model
    def _cron_refresh(self):
        self.recompute()

    # ---------------------------------------------------------- informe semanal
    @api.model
    def _weekly_data(self):
        Partner = self.env['res.partner'].sudo()
        today = fields.Date.context_today(self)
        week_ago = today - timedelta(days=7)
        partners = Partner.search([('inst_is', '=', True)])
        labels = dict(Partner._fields['inst_stage'].selection)
        rows = []
        for key, label in Partner._fields['inst_stage'].selection:
            group = partners.filtered(lambda p, k=key: p.inst_stage == k)
            rows.append({
                'key': key, 'label': label, 'count': len(group),
                'at_risk': len(group.filtered(lambda p: p.inst_alert == 'riesgo')),
                'dormant': len(group.filtered(lambda p: p.inst_alert == 'dormido')),
                'overdue': len(group.filtered(lambda p: p.inst_alert == 'vence')),
                'margin_month': sum(group.mapped('inst_margin_month')),
            })
        logs = self.env['cristal.inst.stage.log'].sudo().search([
            ('date', '>', week_ago), ('stage_from', '!=', False)])
        moves = {}
        for log in logs:
            pair = '%s → %s' % (labels.get(log.stage_from, '?'), labels.get(log.stage_to, '?'))
            moves[pair] = moves.get(pair, 0) + 1
        calls = self.env['cristal.inst.call'].sudo().search([('date', '>', fields.Datetime.now() - timedelta(days=7))])
        top = Partner.search(
            [('inst_is', '=', True), ('inst_stage', '!=', 'descartado'), ('inst_next_step', '!=', False)],
            order='inst_priority desc', limit=8)
        return {
            'today': today, 'rows': rows, 'moves': moves,
            'calls': len(calls), 'talks': len(calls.filtered('is_contact')),
            'kits': len(partners.filtered(lambda p: p.inst_kit_date and p.inst_kit_date > week_ago)),
            'first_orders': len(partners.filtered(lambda p: p.inst_first_order and p.inst_first_order > week_ago)),
            'top': top,
        }

    @api.model
    def _weekly_html(self, data):
        from markupsafe import Markup, escape
        money = lambda v: '$ {:,.0f}'.format(v or 0).replace(',', '.')
        html = Markup('<p><strong>Institucional: resumen de la semana</strong></p>')
        html += Markup('<p>Llamadas registradas: %s (%s con conversación). Kits entregados: %s. '
                       'Primeras compras: %s.</p>') % (data['calls'], data['talks'], data['kits'], data['first_orders'])
        html += Markup('<p><strong>Embudo hoy</strong></p><ul>')
        for row in data['rows']:
            extra = []
            if row['at_risk']:
                extra.append('%s en riesgo' % row['at_risk'])
            if row['dormant']:
                extra.append('%s dormidas' % row['dormant'])
            if row['overdue']:
                extra.append('%s con fecha límite vencida' % row['overdue'])
            if row['margin_month']:
                extra.append('margen por mes %s' % money(row['margin_month']))
            html += Markup('<li>%s: %s%s</li>') % (
                row['label'], row['count'], (' (%s)' % ', '.join(extra)) if extra else '')
        html += Markup('</ul>')
        if data['moves']:
            html += Markup('<p><strong>Cambios de etapa en la semana</strong></p><ul>')
            for pair, qty in sorted(data['moves'].items(), key=lambda kv: -kv[1]):
                html += Markup('<li>%s: %s</li>') % (pair, qty)
            html += Markup('</ul>')
        else:
            html += Markup('<p>Ninguna empresa cambió de etapa esta semana.</p>')
        if data['top']:
            html += Markup('<p><strong>Lo más importante para esta semana</strong></p><ol>')
            for partner in data['top']:
                html += Markup('<li>%s: %s</li>') % (escape(partner.name), escape(partner.inst_next_step))
            html += Markup('</ol>')
        return html

    @api.model
    def _cron_weekly_report(self):
        self.recompute()
        data = self._weekly_data()
        Snapshot = self.env['cristal.inst.snapshot'].sudo()
        Snapshot.search([('date', '=', data['today'])]).unlink()
        Snapshot.create([{
            'date': data['today'], 'stage': row['key'], 'count': row['count'],
            'at_risk': row['at_risk'], 'dormant': row['dormant'], 'overdue': row['overdue'],
            'margin_month': row['margin_month'],
        } for row in data['rows']])
        icp = self.env['ir.config_parameter'].sudo()
        raw = icp.get_param('cristal_institucional.report_user_ids', '18')
        user_ids = [int(x) for x in raw.replace(' ', '').split(',') if x.isdigit()]
        users = self.env['res.users'].sudo().browse(user_ids).exists()
        if users:
            self.env['mail.thread'].sudo().message_notify(
                partner_ids=users.mapped('partner_id').ids,
                subject='Institucional: resumen de la semana',
                body=self._weekly_html(data),
            )
        return True
