# -*- coding: utf-8 -*-
import logging
import re
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, tools

_logger = logging.getLogger(__name__)

MARKETING_GAP_DAYS = 7     # máximo 1 promoción por semana por cliente
ANY_GAP_DAYS = 3           # y nunca dos mensajes automáticos en 3 días
CONVERSION_DAYS = 14
REPOSITION_LEAD_DAYS = 4   # avisar 4 días antes de que se le termine


def _label(family):
    if not family:
        return 'tus productos de limpieza'
    return family.wa_label or 'tu %s' % (family.name or '').lower()


def _first_name(partner):
    """Nombre de pila para el saludo. "Giordano, Oscar Rafael" → "Oscar"; sin coma no se sabe
    el orden ("Funes Monica", "Ana Perez"): se usa la palabra que es un nombre conocido.
    Si no hay ninguna, "qué tal" ("Hola qué tal 👋"; Meta no acepta la variable vacía)."""
    name = (partner.name or '').strip()
    if name.lower().startswith('cliente whatsapp'):
        return 'qué tal'
    if ',' in name:
        candidates = name.split(',', 1)[1].split()[:1]
    else:
        # La palabra que más se usa como nombre que como apellido ("Funes Monica" → Monica)
        known = partner.env['cristal.fid.engine']._known_first_names()
        scored = sorted(((known.get(w.lower(), 0), i, w) for i, w in enumerate(name.split())),
                        key=lambda s: (-s[0], s[1]))
        candidates = [w for score, _i, w in scored if score > 0][:1]
    word = candidates[0] if candidates else ''
    if not word.isalpha():
        return 'qué tal'
    return word[:1].upper() + word[1:].lower()


class CristalFidEngine(models.AbstractModel):
    _name = 'cristal.fid.engine'
    _description = 'Fidelización — motor diario'

    @api.model
    @tools.ormcache()
    def _known_first_names(self):
        """{palabra: veces como nombre − veces como apellido}, sacado de los contactos
        cargados "Apellido, Nombre". Sirve para leer los que no tienen coma."""
        self.env.cr.execute("""
            WITH c AS (SELECT name FROM res_partner WHERE name LIKE '%,%'),
                 f AS (SELECT lower(split_part(trim(split_part(name, ',', 2)), ' ', 1)) w, count(*) n
                         FROM c GROUP BY 1),
                 s AS (SELECT lower(split_part(trim(split_part(name, ',', 1)), ' ', 1)) w, count(*) n
                         FROM c GROUP BY 1)
            SELECT f.w, f.n - coalesce(s.n, 0) FROM f LEFT JOIN s ON s.w = f.w
             WHERE f.n >= 2""")
        return {w: score for w, score in self.env.cr.fetchall()
                if w and len(w) >= 3 and w.isalpha() and score > 0}

    # ── Reglas comunes ─────────────────────────────────────────────
    @api.model
    def _base_domain(self):
        return [('cristal_customer_type', '=', 'cf'), ('cristal_wa_key', '!=', False),
                ('cristal_mkt_optout', '=', False), ('active', '=', True)]

    @api.model
    def _recent_contacts(self, days, categories=None):
        """Partners contactados (enviado o prueba) en los últimos `days` días."""
        since = fields.Datetime.now() - timedelta(days=days)
        domain = [('date', '>=', since), ('state', 'in', ('sent', 'dry_run', 'holdout'))]
        if categories:
            domain.append(('flow_id.category', 'in', categories))
        return set(self.env['cristal.fid.touch'].sudo().search(domain).partner_id.ids)

    @api.model
    def _blocked(self, partner, flow, recent_any, recent_mkt):
        if 'agent_opt_out' in partner._fields and partner.agent_opt_out:
            return True
        if partner.id in recent_any:
            return True
        if flow.category == 'marketing' and (not partner.cristal_mkt_allowed or partner.id in recent_mkt):
            return True
        return False

    @api.model
    def _in_holdout(self, partner, flow):
        return (partner.id * 7919 + flow.id * 104729) % 100 < (flow.holdout_pct or 0)

    # ── Selección de candidatos por flujo ──────────────────────────
    @api.model
    def _candidates_reposicion(self, flow, today):
        """[(partner, variables, family, ref_date)] — se le termina en ≤ 4 días."""
        cycles = self.env['cristal.cf.cycle'].sudo().search([
            ('customer_type', '=', 'cf'),
            ('partner_id.cristal_wa_key', '!=', False),
            ('partner_id.cristal_mkt_optout', '=', False),
            ('partner_id.active', '=', True),
            ('next_due_date', '>=', today),
            ('next_due_date', '<=', today + timedelta(days=REPOSITION_LEAD_DAYS)),
        ], order='next_due_date')
        done = {(t.partner_id.id, t.family_id.id, t.ref_date) for t in self.env['cristal.fid.touch'].sudo().search(
            [('flow_id', '=', flow.id), ('date', '>=', fields.Datetime.now() - timedelta(days=120))])}
        result, seen = [], set()
        for cycle in cycles:
            partner = cycle.partner_id
            if partner.id in seen or (partner.id, cycle.family_id.id, cycle.last_date) in done:
                continue
            if partner.cristal_last_purchase and partner.cristal_last_purchase > cycle.last_date:
                continue    # ya volvió a comprar
            seen.add(partner.id)
            result.append((partner, [_label(cycle.family_id)], cycle.family_id, cycle.last_date))
        return result

    @api.model
    def _candidates_satisfaccion(self, flow, today):
        day = today - timedelta(days=4)
        partners = self.env['res.partner'].sudo().search(self._base_domain() + [
            ('cristal_last_purchase', '=', day), ('cristal_purchases_total', '<=', 3)])
        asked = set(self.env['cristal.fid.touch'].sudo().search([
            ('flow_id', '=', flow.id), ('date', '>=', fields.Datetime.now() - timedelta(days=60))]).partner_id.ids)
        return [(p, [day.strftime('%d/%m')], False, day) for p in partners if p.id not in asked]

    @api.model
    def _candidates_segunda_compra(self, flow, today):
        day = today - timedelta(days=20)
        partners = self.env['res.partner'].sudo().search(self._base_domain() + [
            ('cristal_first_purchase', '=', day), ('cristal_purchases_total', '=', 1)])
        return [(p, [flow.offer_text or 'envío gratis'], False, day) for p in partners]

    @api.model
    def _candidates_reactivacion(self, flow, today, step):
        """Escalera: paso 1 a ciclo+7, paso 2 a 2 ciclos, paso 3 a 3 ciclos (hasta 6 ciclos)."""
        partners = self.env['res.partner'].sudo().search(self._base_domain() + [
            ('cristal_last_purchase', '!=', False), ('cristal_segment', 'in', ('en_riesgo', 'dormido', 'no_perder'))])
        Touch = self.env['cristal.fid.touch'].sudo()
        steps = Touch.search([('flow_code', 'in', ('reactivacion_1', 'reactivacion_2', 'reactivacion_3')),
                              ('partner_id', 'in', partners.ids)])
        by_partner = defaultdict(set)
        for t in steps:
            if t.ref_date == t.partner_id.cristal_last_purchase:
                by_partner[t.partner_id.id].add(t.flow_code)
        Cycle = self.env['cristal.cf.cycle'].sudo()
        result = []
        for p in partners:
            cycle = p.cristal_cycle_days or 35
            recency = (today - p.cristal_last_purchase).days
            if recency > 6 * cycle:
                continue
            sent = by_partner.get(p.id, set())
            due = {1: recency >= cycle + 7, 2: recency >= 2 * cycle, 3: recency >= 3 * cycle}[step]
            prev_ok = step == 1 or 'reactivacion_%s' % (step - 1) in sent
            if not due or not prev_ok or 'reactivacion_%s' % step in sent:
                continue
            fav = Cycle.search([('partner_id', '=', p.id)], order='purchases desc', limit=1)
            variables = [_label(fav.family_id)] if step == 1 else [flow.offer_text or 'un regalo']
            if step == 3:
                variables.append((today + timedelta(days=10)).strftime('%d/%m'))
            result.append((p, variables, fav.family_id, p.cristal_last_purchase))
        return result

    # ── Envío ──────────────────────────────────────────────────────
    @api.model
    def _send(self, flow, partner, variables):
        """Manda la plantilla como el bot, sin pausar a Claudio. Devuelve whatsapp.message o lanza error."""
        mobile = partner.mobile or partner.phone
        Composer = self.env['whatsapp.composer'].sudo().with_context(
            from_cristal_agent=True, active_model='res.partner', active_ids=[partner.id],
            default_res_model='res.partner', default_res_ids=str(partner.id))
        vals = {'res_model': 'res.partner', 'res_ids': str(partner.id),
                'wa_template_id': flow.template_id.id, 'phone': mobile}
        for i, value in enumerate(variables, start=1):
            vals['free_text_%s' % i] = re.sub(r'\s+', ' ', str(value)).strip()[:300]
        Composer.create(vals).action_send_whatsapp_template()
        return self.env['whatsapp.message'].sudo().search([
            ('wa_template_id', '=', flow.template_id.id), ('mobile_number', 'ilike', partner.cristal_wa_key[-8:])],
            order='id desc', limit=1)

    @api.model
    def _cron_run(self, flows=None):
        today = fields.Date.context_today(self)
        flows = flows or self.env['cristal.fid.flow'].sudo().search([])
        Touch = self.env['cristal.fid.touch'].sudo()
        recent_any = self._recent_contacts(ANY_GAP_DAYS)
        recent_mkt = self._recent_contacts(MARKETING_GAP_DAYS, ['marketing'])
        selectors = {
            'reposicion': self._candidates_reposicion,
            'satisfaccion': self._candidates_satisfaccion,
            'segunda_compra': self._candidates_segunda_compra,
            'reactivacion_1': lambda f, d: self._candidates_reactivacion(f, d, 1),
            'reactivacion_2': lambda f, d: self._candidates_reactivacion(f, d, 2),
            'reactivacion_3': lambda f, d: self._candidates_reactivacion(f, d, 3),
        }
        summary = {}
        for flow in flows.sorted('sequence'):
            selector = selectors.get(flow.code)
            if not selector:
                continue
            count = 0
            for partner, variables, family, ref_date in selector(flow, today):
                variables = [_first_name(partner)] + variables   # {{1}} = nombre de pila
                if count >= (flow.daily_limit or 0):
                    break
                if self._blocked(partner, flow, recent_any, recent_mkt):
                    continue
                vals = {'partner_id': partner.id, 'flow_id': flow.id, 'variables': ' | '.join(variables),
                        'family_id': family.id if family else False, 'ref_date': ref_date}
                if self._in_holdout(partner, flow):
                    vals['state'] = 'holdout'
                elif flow.send_enabled and flow.template_id.status == 'approved':
                    try:
                        with self.env.cr.savepoint():
                            msg = self._send(flow, partner, variables)
                        vals.update(state='sent', wa_message_id=msg.id or False)
                    except Exception as e:  # noqa: BLE001 — un cliente con error no frena al resto
                        _logger.warning("fidelización: error enviando %s a %s: %s", flow.code, partner.id, e)
                        vals.update(state='error', error=str(e)[:250])
                else:
                    vals['state'] = 'dry_run'
                Touch.create(vals)
                count += 1
                recent_any.add(partner.id)
                if flow.category == 'marketing':
                    recent_mkt.add(partner.id)
            summary[flow.code] = count
        self._update_conversions()
        _logger.info("fidelización: %s", summary)
        return summary

    # ── Conversiones ───────────────────────────────────────────────
    @api.model
    def _update_conversions(self):
        since = fields.Datetime.now() - timedelta(days=CONVERSION_DAYS + 2)
        touches = self.env['cristal.fid.touch'].sudo().search([
            ('date', '>=', since), ('converted', '=', False), ('state', 'in', ('sent', 'dry_run', 'holdout'))])
        if not touches:
            return
        partners = touches.partner_id
        commercial = {p.id: p.commercial_partner_id.id for p in partners}
        children = self.env['res.partner'].sudo().search([('commercial_partner_id', 'in', list(set(commercial.values())))])
        orders = []
        for model, state in (('pos.order', ('paid', 'done', 'invoiced')), ('sale.order', ('sale',))):
            orders += [(o.partner_id.commercial_partner_id.id, o.date_order, o.amount_total, o.display_name)
                       for o in self.env[model].sudo().search([
                           ('partner_id', 'in', children.ids), ('state', 'in', state),
                           ('date_order', '>=', since), ('amount_total', '>', 0)])]
        for touch in touches:
            com = commercial.get(touch.partner_id.id)
            limit = touch.date + timedelta(days=CONVERSION_DAYS)
            hits = sorted(o for o in orders if o[0] == com and touch.date <= o[1] <= limit)
            if hits:
                first = hits[0]
                touch.write({'converted': True, 'converted_date': first[1].date(),
                             'converted_amount': first[2]})
