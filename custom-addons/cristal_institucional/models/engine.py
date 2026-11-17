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
        data = {p.id: {'orders': [], 'kit_order': False, 'kit_date': False} for p in partners}
        if not partners:
            return data
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
                partner.write(diff)
        _logger.info('Institucional: %s empresas evaluadas, %s con cambios', len(partners), changed)
        return changed

    @api.model
    def _cron_refresh(self):
        self.recompute()
