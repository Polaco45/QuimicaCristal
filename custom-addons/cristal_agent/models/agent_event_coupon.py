# -*- coding: utf-8 -*-
"""v1.82 — Cupones de eventos (HISPANO15 / OULTON15). Joaco, 26/11/2026.

Química Cristal auspicia la Sociedad Española y los premios de RMI (CIMA Oulton). El QR
abre WhatsApp al número de Claudio con "Hola! Quiero mi cupón del 15% - Código X".
Objetivo: sumar consumidores finales a la base y que hagan la primera compra (web o local)
antes del 31/01/2027. Documento: Cadencia_Claudio_Cupones_Eventos.md (docs/plan-cupones-eventos.md).

- `cristal.agent.event`: un evento (código, programa de fidelidad, etiquetas, lista de correo,
  pedido de la mercadería regalada) con la medición calculada.
- `cristal.agent.event.contact`: una persona dentro del circuito de un evento: entrada, pasos
  enviados (A/B/C sin compra, D/E después de la compra), compra y baja.
- Entrada (día 0): el webhook llama a `capture_inbound` → registra todo por código; la
  respuesta la da Claudio con el texto exacto (prompt_builder + control en send_guards).
- `cron_event_coupons` (cada hora): detecta compras con el cupón y manda los pasos en
  horario de lunes a viernes 10-19, por la política de plantillas y con from_cristal_agent.
"""
import logging
import re
import unicodedata
from datetime import date, datetime, time, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

STEP_HOURS = (10, 19)          # lunes a viernes, hora Argentina
MAX_PROACTIVE = 3              # A, B y C
STEPS_NO_PURCHASE = ('A', 'B', 'C')
STEPS_PURCHASE = ('D', 'E')
COUPON_MIN = 20000.0
COUPON_PCT = 15.0

STATES = [
    ('active', 'Sin compra'),
    ('purchased', 'Compró'),
    ('done', 'Terminó (post-compra)'),
    ('finished', 'Terminó sin comprar'),
    ('wholesale', 'Mayorista (flujo normal)'),
    ('opted_out', 'Pidió la baja'),
]
PURCHASE_STEPS = [('day0', 'Día 0 (sin recordatorio)'), ('A', 'Después de A'),
                  ('B', 'Después de B'), ('C', 'Después de C')]

_RE_WHOLESALE = re.compile(
    r'\b(revend\w*|reventa|mayorist\w*|por mayor|distribu\w*|mi negocio|mi comercio|'
    r'mi local|mi almac[eé]n|mi kiosco|mi despensa|tengo (un|una) (negocio|comercio|local|'
    r'almac[eé]n|kiosco|despensa|minimercado|autoservicio))', re.IGNORECASE)
_RE_OPT_OUT = re.compile(
    r'^\W*(baja|dame de baja|darme de baja|no me escriban?( m[aá]s)?|no me manden m[aá]s|'
    r'no quiero (recibir|que me escriban)|stop|basta( de mensajes)?)\W*$', re.IGNORECASE)
_RE_GENERIC_NAME = re.compile(r'^(whatsapp\s*:|\+?\d[\d\s\-]+$)', re.IGNORECASE)


def _norm(text):
    text = unicodedata.normalize('NFKD', (text or '').lower())
    return ''.join(c for c in text if not unicodedata.combining(c))


def _money(v):
    return '$' + f'{int(round(v or 0)):,}'.replace(',', '.')


def _digits(phone):
    return re.sub(r'\D', '', phone or '')[-8:]


def generic_name(name):
    return not (name or '').strip() or bool(_RE_GENERIC_NAME.match((name or '').strip()))


def first_name(partner):
    if generic_name(partner.name):
        return ''
    return (partner.name or '').strip().split()[0].capitalize()


class CristalAgentEvent(models.Model):
    _name = 'cristal.agent.event'
    _description = 'Cristal Agent — Evento con cupón'
    _order = 'date_end desc, id'

    name = fields.Char(string="Evento", required=True)
    code = fields.Char(string="Código del cupón", required=True,
                       help="El código que trae el mensaje del QR (ej. HISPANO15).")
    active = fields.Boolean(default=True)
    code_aliases = fields.Char(
        string="Variantes del código",
        help="Separadas por coma. Se reconocen como el mismo cupón (ej. OUTLON15). El código "
             "que se canjea en la web y en el local es siempre el principal.")
    keywords = fields.Char(
        string="Palabras del evento",
        help="Separadas por coma. Si el mensaje no trae el código pero menciona alguna de "
             "estas palabras junto con 'cupón', se toma este evento.")
    program_id = fields.Many2one('loyalty.program', string="Programa (cupón)")
    date_start = fields.Date(string="Desde", required=True)
    date_end = fields.Date(string="Vence", required=True)
    partner_tag_id = fields.Many2one('res.partner.category', string="Etiqueta de contacto")
    crm_tag_id = fields.Many2one('crm.tag', string="Etiqueta CRM")
    team_id = fields.Many2one('crm.team', string="Equipo de los leads")
    mailing_list_id = fields.Many2one('mailing.list', string="Lista de correo")
    gift_order_id = fields.Many2one('sale.order', string="Mercadería regalada (pedido)")
    reply_text = fields.Text(string="Respuesta del día 0", compute='_compute_reply_text')
    contact_ids = fields.One2many('cristal.agent.event.contact', 'event_id', string="Contactos")

    # ─── Medición (calculada al abrir) ───
    kpi_leads = fields.Integer(string="Contactos entrantes (leads)", compute='_compute_kpis')
    kpi_registered = fields.Integer(string="En el circuito", compute='_compute_kpis')
    kpi_active = fields.Integer(string="Sin compra", compute='_compute_kpis')
    kpi_wholesale = fields.Integer(string="Mayoristas", compute='_compute_kpis')
    kpi_opted_out = fields.Integer(string="Bajas", compute='_compute_kpis')
    kpi_uses = fields.Integer(string="Usos del cupón (todas las ventas)", compute='_compute_kpis')
    kpi_uses_web = fields.Integer(string="Usos en la web", compute='_compute_kpis')
    kpi_uses_pos = fields.Integer(string="Usos en el local", compute='_compute_kpis')
    kpi_revenue = fields.Float(string="Facturación sin IVA", compute='_compute_kpis')
    kpi_buyers = fields.Integer(string="Contactos que compraron", compute='_compute_kpis')
    kpi_unlinked = fields.Integer(string="Usos sin contacto vinculado", compute='_compute_kpis')
    kpi_conversion = fields.Float(string="Conversión (%)", compute='_compute_kpis')
    kpi_by_step = fields.Char(string="Compras por paso", compute='_compute_kpis')
    kpi_gift_cost = fields.Float(string="Costo mercadería regalada", compute='_compute_kpis')
    kpi_ratio = fields.Float(string="Facturación / costo", compute='_compute_kpis')
    kpi_summary = fields.Html(string="Resumen", compute='_compute_kpis', sanitize=False)

    _sql_constraints = [('code_uniq', 'unique(code)', 'Ya hay un evento con ese código.')]

    def _compute_reply_text(self):
        for ev in self:
            ev.reply_text = ev.coupon_message()

    def coupon_message(self):
        self.ensure_one()
        return (f"¡Hola! Gracias por escribirnos 🙌 Tu cupón es *{self.code}*: "
                f"{COUPON_PCT:.0f}% de descuento en tu primera compra desde {_money(COUPON_MIN)}.\n"
                f"🛒 Web: ingresalo al pagar en quimicacristal.com.ar\n"
                f"🏪 Local: mostralo en San Martín 2350, Río Cuarto\n"
                f"Válido hasta el {self.date_end:%d/%m/%Y}.")

    def is_open(self, day=None):
        self.ensure_one()
        day = day or fields.Date.context_today(self)
        return self.active and self.date_start <= day <= self.date_end

    # ─── Detección en el texto entrante ───
    def all_codes(self):
        """Código del cupón + variantes que también se reconocen (ej. OUTLON15 por OULTON15)."""
        self.ensure_one()
        codes = [self.code] + [c.strip() for c in (self.code_aliases or '').split(',')]
        return [re.sub(r'[\s\-_.]', '', c).upper() for c in codes if c and c.strip()]

    @api.model
    def match_text(self, text):
        """Evento al que se refiere el texto (por código, o por palabra del evento + cupón)."""
        if not text:
            return self.browse()
        flat = re.sub(r'[\s\-_.]', '', _norm(text)).upper()
        events = self.sudo().search([])
        for ev in events:
            for code in ev.all_codes():
                if code in flat:
                    return ev
        plain = _norm(text)
        if 'cupon' not in plain and '15%' not in plain:
            return self.browse()
        for ev in events:
            for kw in (ev.keywords or '').split(','):
                kw = _norm(kw.strip())
                if kw and re.search(r'\b' + re.escape(kw) + r'\b', plain):
                    return ev
        return self.browse()

    # ─── Ventas con el cupón ───
    def _coupon_orders(self):
        """[{kind, order, partner, amount_untaxed, date}] de todas las ventas con el cupón."""
        self.ensure_one()
        out = []
        if not self.program_id:
            return out
        SOL = self.env['sale.order.line'].sudo()
        if 'reward_id' in SOL._fields:
            lines = SOL.search([('reward_id.program_id', '=', self.program_id.id),
                                ('order_id.state', '=', 'sale')])
            for o in lines.mapped('order_id'):
                out.append({'kind': 'web', 'order': o, 'partner': o.partner_id,
                            'amount_untaxed': o.amount_untaxed, 'date': o.date_order,
                            'ref': o.name})
        if 'pos.order.line' in self.env:
            POL = self.env['pos.order.line'].sudo()
            if 'reward_id' in POL._fields:
                lines = POL.search([('reward_id.program_id', '=', self.program_id.id),
                                    ('order_id.state', 'in', ('paid', 'done', 'invoiced'))])
                for o in lines.mapped('order_id'):
                    out.append({'kind': 'pos', 'order': o, 'partner': o.partner_id,
                                'amount_untaxed': (o.amount_total or 0.0) - (o.amount_tax or 0.0),
                                'date': o.date_order, 'ref': o.name})
        return out

    def _gift_cost(self):
        self.ensure_one()
        cost = 0.0
        for line in self.gift_order_id.order_line:
            if not line.product_id:
                continue
            unit = line.purchase_price if 'purchase_price' in line._fields and line.purchase_price \
                else line.product_id.standard_price
            cost += (unit or 0.0) * (line.product_uom_qty or 0.0)
        return cost

    def _compute_kpis(self):
        Lead = self.env['crm.lead'].sudo().with_context(active_test=False)
        for ev in self:
            contacts = ev.contact_ids
            orders = ev._coupon_orders() if ev.id else []
            linked = set(contacts.filtered('purchase_ref').mapped('purchase_ref'))
            buyers = contacts.filtered(lambda c: c.purchase_date)
            leads = Lead.search_count([('tag_ids', 'in', ev.crm_tag_id.ids)]) if ev.crm_tag_id else 0
            ev.kpi_leads = leads
            ev.kpi_registered = len(contacts)
            ev.kpi_active = len(contacts.filtered(lambda c: c.state == 'active'))
            ev.kpi_wholesale = len(contacts.filtered(lambda c: c.state == 'wholesale'))
            ev.kpi_opted_out = len(contacts.filtered(lambda c: c.state == 'opted_out'))
            ev.kpi_uses = len(orders)
            ev.kpi_uses_web = len([o for o in orders if o['kind'] == 'web'])
            ev.kpi_uses_pos = len([o for o in orders if o['kind'] == 'pos'])
            ev.kpi_revenue = sum(o['amount_untaxed'] for o in orders)
            ev.kpi_buyers = len(buyers)
            ev.kpi_unlinked = len([o for o in orders if o['ref'] not in linked])
            base = leads or len(contacts)
            ev.kpi_conversion = (100.0 * len(buyers) / base) if base else 0.0
            steps = {k: len(buyers.filtered(lambda c, k=k: c.purchase_step == k))
                     for k, _l in PURCHASE_STEPS}
            ev.kpi_by_step = (f"día 0: {steps['day0']} · A: {steps['A']} · B: {steps['B']} · "
                              f"C: {steps['C']} · sin vincular: {ev.kpi_unlinked}")
            ev.kpi_gift_cost = ev._gift_cost()
            ev.kpi_ratio = (ev.kpi_revenue / ev.kpi_gift_cost) if ev.kpi_gift_cost else 0.0
            ev.kpi_summary = ev._summary_html()

    def _summary_html(self):
        self.ensure_one()
        return (f"<p><b>🎟️ {self.code}</b> — {self.name}<br/>"
                f"Contactos: <b>{self.kpi_leads}</b> (sin compra {self.kpi_active}, "
                f"mayoristas {self.kpi_wholesale}, bajas {self.kpi_opted_out}) · "
                f"Usos del cupón: <b>{self.kpi_uses}</b> (web {self.kpi_uses_web}, local "
                f"{self.kpi_uses_pos}) · Facturación sin IVA: <b>{_money(self.kpi_revenue)}</b><br/>"
                f"Conversión: <b>{self.kpi_conversion:.1f}%</b> ({self.kpi_buyers} contactos "
                f"compraron) · Compras por paso: {self.kpi_by_step}<br/>"
                f"Mercadería regalada: {_money(self.kpi_gift_cost)} · Facturación/costo: "
                f"<b>{self.kpi_ratio:.2f}</b></p>")

    def action_open_contacts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'cristal_agent.action_cristal_agent_event_contact')
        action['domain'] = [('event_id', '=', self.id)]
        action['context'] = {}
        return action

    def action_selftest(self):
        """Corre el autotest del circuito (se revierte todo, no sale ningún WhatsApp)."""
        from odoo.exceptions import UserError
        results = self.env['cristal.agent.event.contact'].selftest()
        ok = sum(1 for _n, good, _d in results if good)
        lines = [f"{'✅' if good else '❌'} {n}: {d}" for n, good, d in results]
        raise UserError(f"Autotest cupones de eventos: {ok}/{len(results)} OK\n\n" + "\n".join(lines))

    @api.model
    def weekly_report_html(self):
        """Sección del informe de los lunes: eventos vigentes o vencidos hace < 30 días."""
        today = fields.Date.context_today(self)
        events = self.sudo().search([('date_start', '<=', today),
                                     ('date_end', '>=', today - timedelta(days=30))])
        if not events:
            return ''
        return ("<p><b>🎟️ Cupones de eventos</b></p>"
                + ''.join(ev._summary_html() for ev in events))


class CristalAgentEventContact(models.Model):
    _name = 'cristal.agent.event.contact'
    _description = 'Cristal Agent — Contacto de un cupón de evento'
    _order = 'entry_date desc, id desc'
    _rec_name = 'partner_id'

    event_id = fields.Many2one('cristal.agent.event', required=True, ondelete='cascade',
                               string="Evento")
    code = fields.Char(related='event_id.code', store=True, string="Código")
    partner_id = fields.Many2one('res.partner', required=True, ondelete='cascade', index=True,
                                 string="Contacto")
    mobile = fields.Char(related='partner_id.mobile', string="Celular")
    lead_id = fields.Many2one('crm.lead', string="Lead", ondelete='set null')
    entry_date = fields.Datetime(string="Entrada", required=True, default=fields.Datetime.now)
    state = fields.Selection(STATES, string="Estado", default='active', required=True)
    first_text = fields.Char(string="Primer mensaje")
    coupon_sent_at = fields.Datetime(string="Cupón enviado")
    name_asked = fields.Boolean(string="Nombre pedido")
    a_sent_at = fields.Datetime(string="A enviado")
    b_sent_at = fields.Datetime(string="B enviado")
    c_sent_at = fields.Datetime(string="C enviado")
    d_sent_at = fields.Datetime(string="D enviado")
    e_sent_at = fields.Datetime(string="E enviado")
    skipped_steps = fields.Char(string="Pasos salteados")
    proactive_count = fields.Integer(string="Mensajes proactivos", compute='_compute_proactive',
                                     store=True)
    last_note = fields.Char(string="Última novedad")
    purchase_date = fields.Datetime(string="Compra")
    purchase_ref = fields.Char(string="Pedido")
    purchase_kind = fields.Selection([('web', 'Web'), ('pos', 'Local')], string="Canal")
    purchase_amount = fields.Float(string="Importe sin IVA")
    purchase_product = fields.Char(string="Producto principal")
    purchase_step = fields.Selection(PURCHASE_STEPS, string="Compró después de")
    feedback = fields.Text(string="Respuesta post-compra")

    _sql_constraints = [('event_partner_uniq', 'unique(event_id, partner_id)',
                         'El contacto ya está registrado en ese evento.')]

    @api.depends('a_sent_at', 'b_sent_at', 'c_sent_at')
    def _compute_proactive(self):
        for c in self:
            c.proactive_count = len([1 for f in ('a_sent_at', 'b_sent_at', 'c_sent_at') if c[f]])

    # ─────────────────────────── Entrada (día 0) ───────────────────────────
    @api.model
    def capture_inbound(self, partner, text, when=None):
        """Lo llama el webhook con cada mensaje entrante (antes del takeover y del debounce).
        Registra el contacto si trae un código o una mención de evento, y procesa bajas
        de quien ya está en el circuito. Nunca llama a la IA ni manda WhatsApp."""
        if not partner or not text:
            return self.browse()
        self = self.sudo()
        mine = self.search([('partner_id', '=', partner.id),
                            ('state', 'in', ('active', 'purchased'))])
        if mine and _RE_OPT_OUT.match(text.strip()):
            partner.sudo().set_agent_opt_out(f'pidió la baja ("{text.strip()[:80]}")')
            return mine
        # Respuesta al paso D ("¿qué tal los productos?"): queda en el circuito y en observaciones.
        for c in mine.filtered(lambda x: x.d_sent_at and not x.feedback and not x.e_sent_at):
            c.feedback = text.strip()[:500]
            if hasattr(partner, 'append_agent_observation'):
                partner.sudo().append_agent_observation(
                    f"🎟️ Opinión después de comprar con {c.code}: {text.strip()[:200]}")
        if mine and _RE_WHOLESALE.search(text):
            mine.filtered(lambda c: c.state == 'active').mark_wholesale(text)
        event = self.env['cristal.agent.event'].match_text(text)
        if not event:
            return mine
        return self.register(partner, event, text=text, when=when)

    @api.model
    def register(self, partner, event, text='', when=None):
        self = self.sudo()
        partner = partner.sudo()
        contact = self.search([('event_id', '=', event.id), ('partner_id', '=', partner.id)],
                              limit=1)
        if contact:
            return contact
        when = when or fields.Datetime.now()
        if not event.is_open(fields.Date.context_today(self)):
            _logger.info("🎟️ %s pidió %s pero el evento no está vigente.", partner.name, event.code)
            return self.browse()
        wholesale = bool(_RE_WHOLESALE.search(text or '')) or self._is_wholesale_partner(partner)
        contact = self.create({
            'event_id': event.id, 'partner_id': partner.id, 'entry_date': when,
            'first_text': (text or '')[:250],
            'state': 'wholesale' if wholesale else 'active',
            'last_note': "Mayorista: sigue el flujo mayorista" if wholesale else False,
        })
        try:
            with self.env.cr.savepoint():
                contact._register_side_effects()
        except Exception as e:  # noqa: BLE001 — nunca romper el webhook
            _logger.exception("🎟️ Registro de %s en %s incompleto: %s", partner.name, event.code, e)
        _logger.info("🎟️ %s entró por el cupón %s (%s).", partner.name, event.code, contact.state)
        return contact

    @api.model
    def _is_wholesale_partner(self, partner):
        p = partner.commercial_partner_id
        if 'cristal_wholesale_buyer' in p._fields and p.cristal_wholesale_buyer:
            return True
        if any(_norm(t.name) == 'mayorista' for t in (p.category_id | partner.category_id)):
            return True
        return False

    def _register_side_effects(self):
        for c in self:
            ev, partner = c.event_id, c.partner_id
            vals = {}
            if ev.partner_tag_id:
                vals['category_id'] = [(4, ev.partner_tag_id.id)]
            if 'agent_origin_code' in partner._fields and \
                    partner.agent_origin_code in (False, '', 'ORGANICO'):
                vals['agent_origin_code'] = ev.code
            if vals:
                partner.write(vals)
            if hasattr(partner, 'append_agent_observation'):
                partner.append_agent_observation(
                    f"🎟️ Origen: evento {ev.name} ({ev.code}), {fields.Date.context_today(c):%d/%m/%Y}")
            c.lead_id = c._create_lead()
            c._add_to_mailing_list()

    def lead_name(self):
        self.ensure_one()
        nm = '' if generic_name(self.partner_id.name) else self.partner_id.name.strip()
        return f"Cupón evento – {self.code} – {nm or (self.partner_id.mobile or 'sin nombre')}"

    def _create_lead(self):
        self.ensure_one()
        ev = self.event_id
        config = self.env['cristal.agent.config'].sudo().get_active()
        bot_uid = config.bot_user_id.id if config and config.bot_user_id else 1
        vals = {
            'name': self.lead_name(), 'partner_id': self.partner_id.id, 'type': 'opportunity',
            'user_id': bot_uid, 'team_id': ev.team_id.id or False,
            'tag_ids': [(4, ev.crm_tag_id.id)] if ev.crm_tag_id else False,
            'description': (f"Entró por el cupón {ev.code} ({ev.name}) el "
                            f"{fields.Date.context_today(self):%d/%m/%Y}. Mensaje: "
                            f"{self.first_text or ''}"),
        }
        if 'utm.source' in self.env and 'source_id' in self.env['crm.lead']._fields:
            Source = self.env['utm.source'].sudo()
            src = Source.search([('name', '=', ev.code)], limit=1) or Source.create({'name': ev.code})
            vals['source_id'] = src.id
        if not vals['tag_ids']:
            vals.pop('tag_ids')
        return self.env['crm.lead'].sudo().with_context(
            mail_create_nosubscribe=True, from_cristal_agent=True).create(vals)

    def _add_to_mailing_list(self):
        self.ensure_one()
        mlist = self.event_id.mailing_list_id
        if not mlist or 'mailing.contact' not in self.env:
            return
        partner = self.partner_id
        MC = self.env['mailing.contact'].sudo()
        mc = MC.search([('list_ids', 'in', mlist.id), ('name', '=', partner.name)], limit=1)
        if partner.email:
            mc = mc or MC.search([('email', '=', partner.email)], limit=1)
        if not mc:
            mc = MC.create({'name': partner.name, 'email': partner.email or False})
        if mlist not in mc.list_ids:
            mc.write({'list_ids': [(4, mlist.id)]})

    def mark_wholesale(self, text=''):
        for c in self:
            c.write({'state': 'wholesale',
                     'last_note': f"Mayorista: sigue el flujo mayorista ({(text or '')[:60]})"})

    def rename_leads(self):
        for c in self.filtered('lead_id'):
            c.lead_id.sudo().write({'name': c.lead_name()})

    def opt_out(self, reason=''):
        """Baja del circuito y de la lista del evento."""
        for c in self.sudo():
            c.write({'state': 'opted_out', 'last_note': f"Baja: {reason}"[:200]})
            mlist = c.event_id.mailing_list_id
            if mlist and 'mailing.subscription' in self.env:
                subs = self.env['mailing.subscription'].sudo().search([
                    ('list_id', '=', mlist.id), ('contact_id.name', '=', c.partner_id.name)])
                if c.partner_id.email:
                    subs |= self.env['mailing.subscription'].sudo().search([
                        ('list_id', '=', mlist.id), ('contact_id.email', '=', c.partner_id.email)])
                subs.write({'opt_out': True})

    # ─────────────────────────── Prompt y controles ───────────────────────────
    @api.model
    def prompt_lines(self, partner):
        """Líneas para el contexto del cliente (bloque dinámico del prompt)."""
        contacts = self.sudo().search([('partner_id', '=', partner.id)])
        if not contacts:
            return []
        today = fields.Date.context_today(self)
        lines = []
        for c in contacts:
            ev = c.event_id
            if not ev.is_open(today):
                lines.append(f"- 🎟️ Cupón de evento {c.code}: VENCIÓ el {ev.date_end:%d/%m/%Y}. "
                             f"Si lo nombra, decile que ya venció y derivalo a la web "
                             f"(quimicacristal.com.ar) o al local.")
                continue
            if c.state == 'wholesale':
                lines.append(f"- 🎟️ Pidió el cupón {c.code} pero es MAYORISTA / revendedor: si "
                             f"todavía no se lo diste, dáselo con el texto de abajo y después "
                             f"seguí el flujo mayorista normal.")
            if not c.coupon_sent_at:
                lines.append(
                    f"- 🎟️ CUPÓN DE EVENTO {c.code} ({ev.name}) — lo acaba de pedir. Contestale "
                    f"YA con este texto, tal cual, sin preguntas previas:\n«{ev.coupon_message()}»")
                if c.state != 'wholesale':
                    if generic_name(partner.name) and not c.name_asked:
                        lines.append("  En el mismo mensaje, al final, pedile UNA sola vez el "
                                     "nombre: \"¿Me decís tu nombre así te agendamos?\". Cuando "
                                     "te lo diga, guardalo con update_partner(name=...).")
                    lines.append("  Es CONSUMIDOR FINAL: atendelo como tal en esta misma charla, "
                                 "sin calificarlo ni derivarlo. Si consulta, recomendale para "
                                 "la casa: de fabricación propia jabón líquido para ropa, "
                                 "suavizante, perfume para ropa, desodorante de pisos y "
                                 "detergente; también lavandina (fraccionada, no la presentes "
                                 "como fabricación propia) y los combos para la casa. Que use "
                                 "el cupón en la web (tiene envío) o en el local. El "
                                 "registro (etiqueta, oportunidad, lista) lo hace el sistema. "
                                 "NO hay recordatorios ni campaña aparte: no agendes "
                                 "seguimientos ni actividades por el cupón.")
            elif c.state in ('active', 'purchased', 'done', 'finished'):
                lines.append(
                    f"- 🎟️ Pidió el cupón {c.code} el {fields.Datetime.context_timestamp(c, c.entry_date):%d/%m}"
                    f" (ya se lo mandaste). Estado: {dict(STATES)[c.state]}. No se lo vuelvas a "
                    f"mandar salvo que lo pida. Atendelo como consumidor final: ofrecele "
                    f"productos y combos para la casa y que canjee el cupón en la web o en el "
                    f"local (pedido por WhatsApp con envío → escalá a Joaco; nunca armes un "
                    f"pedido con el 15%). Si pide la baja: mark_opt_out(kind=no_escribir) y "
                    f"confirmale la baja en una línea.")
                if generic_name(partner.name) and c.name_asked:
                    lines.append("  Si en este mensaje te dice su nombre, guardalo con "
                                 "update_partner(name=...).")
        return lines

    @api.model
    def guard(self, partner, plain):
        """Control al enviar. Devuelve None o {'guard', 'instruction', 'fixed'(str→str)}."""
        if not partner:
            return None
        flat = re.sub(r'[\s\-_.*]', '', _norm(plain or '')).upper()
        Event = self.env['cristal.agent.event'].sudo()
        contacts = self.sudo().search([('partner_id', '=', partner.id)])
        mine_codes = set(contacts.mapped('code'))
        # 1) Nombra un cupón de evento que este cliente nunca pidió.
        for ev in Event.search([]):
            if ev.code.upper() in flat and ev.code not in mine_codes:
                return {'guard': 'cupon_no_pedido', 'instruction': (
                    f"NO MANDÉ EL MENSAJE: el cupón {ev.code} es solo para quien lo pide desde "
                    f"el evento. No lo ofrezcas en otras conversaciones. Mandalo sin el cupón."),
                    'strip': ev.code}
        today = fields.Date.context_today(self)
        for c in contacts.filtered(lambda x: not x.coupon_sent_at and x.event_id.is_open(today)):
            if c.code.upper() not in flat:
                return {'guard': 'cupon_evento', 'instruction': (
                    f"NO MANDÉ EL MENSAJE: este cliente pidió el cupón {c.code} y la respuesta "
                    f"tiene que darle el cupón con el texto indicado en su contexto "
                    f"(🎟️ CUPÓN DE EVENTO). Volvé a mandarlo con ese texto."),
                    'prepend': c.event_id.coupon_message()}
        return None

    @api.model
    def note_outbound(self, partner, plain):
        """Después de pasar los controles: marca cupón enviado / nombre pedido."""
        if not partner:
            return
        flat = re.sub(r'[\s\-_.*]', '', _norm(plain or '')).upper()
        low = _norm(plain or '')
        for c in self.sudo().search([('partner_id', '=', partner.id)]):
            vals = {}
            if not c.coupon_sent_at and c.code.upper() in flat:
                vals['coupon_sent_at'] = fields.Datetime.now()
            if not c.name_asked and 'tu nombre' in low:
                vals['name_asked'] = True
            if vals:
                c.write(vals)

    # ─────────────────────────── Fechas de los pasos ───────────────────────────
    @api.model
    def _is_business_day(self, d):
        from ..services.helpers import closed_day_reason
        return d.weekday() < 5 and not closed_day_reason(self.env, d)

    def _local_date(self, dt):
        return fields.Datetime.context_timestamp(self.with_context(tz='America/Argentina/Cordoba'),
                                                 dt).date()

    def step_dates(self):
        """{'A','B','C'} fechas (AR) en que corresponde cada paso sin compra; None = no va."""
        self.ensure_one()
        ev = self.event_id
        entry = self._local_date(self.entry_date)
        anchor = ev.date_end - timedelta(days=7)               # 24/01 para el 31/01
        cap = ev.date_end - timedelta(days=2)                  # 29/01: último aviso útil
        c_day = max(anchor, entry + timedelta(days=25))
        c_day = min(c_day, cap)
        d = c_day
        while not self._is_business_day(d) and d < cap:        # 24/01 domingo → lunes 25/01
            d += timedelta(days=1)
        while not self._is_business_day(d) and d > entry:
            d -= timedelta(days=1)
        c_day = d if d > entry else None
        res = {'C': c_day}
        for step, days in (('A', 3), ('B', 10)):
            due = entry + timedelta(days=days)
            res[step] = due if (c_day and due < c_day) else None
        return res

    # ─────────────────────────── Cron ───────────────────────────
    @api.model
    def _in_step_hours(self, now=None):
        from ..services.helpers import now_ar
        now = now or now_ar(self.env)
        return self._is_business_day(now.date()) and STEP_HOURS[0] <= now.hour < STEP_HOURS[1]

    @api.model
    def cron_event_coupons(self, limit=60):
        self = self.sudo()
        self._detect_purchases()
        self._sync_wholesale()
        # v1.82.1 — Joaco (26/11): "no campaña aparte". Sin recordatorios ni plantillas:
        # el cron solo mide compras. Los pasos quedan en el código por si algún día se piden.
        if self.env['ir.config_parameter'].sudo().get_param(
                'cristal_agent.event_coupon_followups', '0') != '1':
            return
        if not self._in_step_hours():
            _logger.info("🎟️ Cupones de eventos: fuera de horario (L-V 10-19); solo compras.")
            return
        sent = 0
        for c in self.search([('state', 'in', ('active', 'purchased'))], order='entry_date'):
            if sent >= limit:
                break
            try:
                if c._run_due_step():
                    sent += 1
            except Exception as e:  # noqa: BLE001
                _logger.exception("🎟️ Paso de %s falló: %s", c.partner_id.name, e)
        _logger.info("🎟️ Cupones de eventos: %s mensajes enviados.", sent)

    def _match_order(self, info):
        """¿Esta venta con el cupón es de este contacto? (partner, empresa o celular)."""
        self.ensure_one()
        op = info['partner']
        if not op:
            return False
        mine = self.partner_id.commercial_partner_id
        if op.commercial_partner_id == mine or op == self.partner_id:
            return True
        my_digits = _digits(self.partner_id.mobile or self.partner_id.phone)
        return bool(my_digits) and my_digits in (_digits(op.mobile), _digits(op.phone))

    @api.model
    def _detect_purchases(self):
        events = self.env['cristal.agent.event'].sudo().search([])
        for ev in events:
            pending = self.search([('event_id', '=', ev.id), ('purchase_date', '=', False),
                                   ('state', 'in', ('active', 'finished', 'opted_out', 'wholesale'))])
            if not pending:
                continue
            used = {c.purchase_ref for c in ev.contact_ids if c.purchase_ref}
            for info in sorted(ev._coupon_orders(), key=lambda i: i['date'] or datetime.min):
                if info['ref'] in used:
                    continue
                for c in pending:
                    if not c.purchase_date and c._match_order(info):
                        c._set_purchase(info)
                        used.add(info['ref'])
                        break

    def _set_purchase(self, info):
        self.ensure_one()
        last = 'day0'
        for step, f in (('A', 'a_sent_at'), ('B', 'b_sent_at'), ('C', 'c_sent_at')):
            if self[f] and self[f] <= (info['date'] or fields.Datetime.now()):
                last = step
        vals = {'purchase_date': info['date'] or fields.Datetime.now(),
                'purchase_ref': info['ref'], 'purchase_kind': info['kind'],
                'purchase_amount': info['amount_untaxed'],
                'purchase_product': self._main_product(info['order']),
                'purchase_step': last,
                'last_note': f"Compró con el cupón ({info['ref']})"}
        if self.state in ('active', 'finished'):
            vals['state'] = 'purchased'
        self.write(vals)
        if self.lead_id and self.lead_id.active:
            try:
                self.lead_id.sudo().action_set_won()
            except Exception as e:  # noqa: BLE001
                _logger.warning("🎟️ No pude marcar ganado el lead %s: %s", self.lead_id.id, e)
        _logger.info("🎟️ %s compró con %s (%s).", self.partner_id.name, self.code, info['ref'])

    @api.model
    def _main_product(self, order):
        lines = order.lines if order._name == 'pos.order' else order.order_line
        best, amount = None, 0.0
        for l in lines:
            if not l.product_id or getattr(l, 'reward_id', False) or \
                    getattr(l, 'is_reward_line', False) or getattr(l, 'is_delivery', False):
                continue
            if getattr(l, 'combo_parent_id', False) or getattr(l, 'linked_line_id', False):
                continue
            sub = l.price_subtotal or 0.0
            if best is None or sub > amount:
                best, amount = l.product_id, sub
        if not best:
            return False
        return re.sub(r'^\[[^\]]*\]\s*', '', best.display_name or '')[:120]

    @api.model
    def _sync_wholesale(self):
        """Si Claudio lo marcó mayorista después (etiqueta / comprador mayorista), sale del circuito."""
        for c in self.search([('state', '=', 'active')]):
            if self._is_wholesale_partner(c.partner_id):
                c.mark_wholesale("marcado como mayorista")

    def _skip(self, steps, note):
        self.ensure_one()
        done = set(filter(None, (self.skipped_steps or '').split(',')))
        done.update(steps)
        self.write({'skipped_steps': ','.join(sorted(done)), 'last_note': note[:200]})

    def _pending(self, step):
        self.ensure_one()
        return not self[f'{step.lower()}_sent_at'] and \
            step not in (self.skipped_steps or '').split(',')

    def _due_step(self, today):
        """(step, due_date) del paso que toca hoy, o (None, None). Saltea los vencidos."""
        self.ensure_one()
        if self.state == 'active':
            dates = self.step_dates()
            due = [(s, dates[s]) for s in STEPS_NO_PURCHASE if dates.get(s)]
            never = [s for s in STEPS_NO_PURCHASE if not dates.get(s) and self._pending(s)]
            if never:
                self._skip(never, f"Pasos {', '.join(never)} no van (entró tarde)")
            ready = [(s, d) for s, d in due if d <= today and self._pending(s)]
            if not ready:
                if all(not self._pending(s) for s, _d in due) or not due:
                    self.write({'state': 'finished',
                                'last_note': "Terminó A-B-C sin comprar"})
                return None, None
            # Si se juntaron varios (postergados), va el último y los anteriores se saltean.
            if len(ready) > 1:
                self._skip([s for s, _d in ready[:-1]], "Salteado: se juntó con el siguiente")
            return ready[-1]
        if self.state == 'purchased' and self.purchase_date:
            bought = self._local_date(self.purchase_date)
            for step, days in (('D', 3), ('E', 30)):
                if self._pending(step):
                    due = bought + timedelta(days=days)
                    if due <= today:
                        return step, due
                    return None, None
            self.write({'state': 'done', 'last_note': "Terminó D-E: pasa a la base general CF"})
        return None, None

    def _blocked(self):
        """Motivo para no escribirle hoy (o None)."""
        self.ensure_one()
        p = self.partner_id
        if p.agent_opt_out:
            if self.state in ('active', 'purchased'):
                self.opt_out(p.agent_opt_out_reason or 'no contactar')
            return "no contactar"
        mem = getattr(p, 'agent_memory_id', False)
        if mem and mem.is_takeover_active():
            return "intervención humana activa"
        from ..services.helpers import is_24h_window_open
        try:
            if is_24h_window_open(self.env, p):
                return "está conversando (ventana abierta): se posterga"
        except Exception:  # noqa: BLE001
            pass
        return None

    def _run_due_step(self):
        self.ensure_one()
        from ..services.helpers import now_ar
        today = now_ar(self.env).date()
        if self.state == 'active' and not self.event_id.is_open(today):
            self.write({'state': 'finished', 'last_note': "El cupón venció"})
            return False
        step, due = self._due_step(today)
        if not step:
            return False
        if step in STEPS_NO_PURCHASE and self.proactive_count >= MAX_PROACTIVE:
            self.write({'state': 'finished', 'last_note': "Tope de 3 mensajes"})
            return False
        why = self._blocked()
        if why:
            self.write({'last_note': f"{step} postergado: {why}"[:200]})
            return False
        cadence = self.env['cristal.agent.cadence'].sudo().search([
            ('trigger_event', 'in', ('event_coupon', 'event_coupon_purchase')),
            ('step_code', '=', step), ('active', '=', True)], limit=1)
        if not cadence:
            self.write({'last_note': f"{step}: cadencia apagada"})
            return False
        tpl = cadence.whatsapp_template_id
        if not tpl or tpl.status != 'approved':
            self.write({'last_note': f"{step}: plantilla {tpl.template_name or '(sin plantilla)'} "
                                     f"no aprobada por Meta"[:200]})
            return False
        variables = self._variables(step)
        if variables is None:
            return False
        from ..services.tool_registry import ToolRegistry
        from ..services import tools  # noqa: F401 — registra las tools
        tool = ToolRegistry.get('send_whatsapp_template')
        res = tool.execute(env=self.env, run=None, partner_id=self.partner_id.id,
                           template_name=tpl.template_name, variables=variables) or {}
        if res.get('ok'):
            self.write({f'{step.lower()}_sent_at': fields.Datetime.now(),
                        'last_note': f"{step} enviado ({tpl.template_name})"})
            return True
        note = res.get('policy') or res.get('error') or 'no enviado'
        self.write({'last_note': f"{step} no salió: {note}"[:200]})
        return False

    def _variables(self, step):
        self.ensure_one()
        name = first_name(self.partner_id) or "qué tal"
        if step in ('A', 'C'):
            return [name, self.code]
        if step == 'B':
            combo = self.combo_text()
            if not combo:
                self._skip(['B'], "B salteado: no hay combo con stock para armar")
                return None
            return [name, self.code, combo]
        if step == 'D':
            day = self._local_date(self.purchase_date)
            return [name, f"{day:%d/%m}"]
        if step == 'E':
            return [name, (self.purchase_product or 'los productos que llevaste').lower()]
        return None

    @api.model
    def combo_text(self):
        """Texto de {{3}} de B: combos reales (lista CF) con el 15% aplicado, ≥ $20.000."""
        from ..services import cf_combos
        try:
            data = cf_combos.catalog(self.env)
        except Exception as e:  # noqa: BLE001
            _logger.warning("🎟️ No pude leer los combos: %s", e)
            return ''
        ok = [c for c in data if not c['missing']]
        if not ok:
            return ''
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'cristal_agent.event_coupon_combo_ids', '')
        wanted = [int(x) for x in re.findall(r'\d+', raw or '')]
        by_id = {c['product'].id: c for c in ok}
        chosen = [by_id[i] for i in wanted if i in by_id]
        if not chosen:
            chosen = [min(ok, key=lambda c: abs(c['price'] - COUPON_MIN))]
        picked, total = [], 0.0
        for c in chosen:
            if total >= COUPON_MIN:
                break
            picked.append(c)
            total += c['price']
        if total < COUPON_MIN:
            rest = sorted((c for c in ok if c not in picked), key=lambda c: c['price'])
            extra = next((c for c in rest if total + c['price'] >= COUPON_MIN), rest[-1] if rest else None)
            if extra:
                picked.append(extra)
                total += extra['price']
        if total < COUPON_MIN:
            return ''
        names = ' + '.join(c['name'] for c in picked)
        final = total * (1 - COUPON_PCT / 100.0)
        return (f"{names}, de {_money(total)} a {_money(final)} con el {COUPON_PCT:.0f}% aplicado")

    # ─────────────────────────── Autotest ───────────────────────────
    @api.model
    def selftest(self):
        """Casos del circuito en un savepoint que se revierte. Devuelve [(caso, ok, detalle)].
        Ningún WhatsApp sale: se reemplaza el envío de plantillas por uno simulado."""
        results = []

        class _Rollback(Exception):
            pass
        try:
            with self.env.cr.savepoint():
                self._selftest_cases(results)
                raise _Rollback()
        except _Rollback:
            pass
        return results

    def _selftest_cases(self, results):
        env = self.env
        Event = env['cristal.agent.event'].sudo()
        Contact = self.sudo()
        Partner = env['res.partner'].sudo()

        def case(name, fn):
            try:
                with env.cr.savepoint():
                    results.append((name, True, fn() or 'OK'))
            except Exception as e:  # noqa: BLE001
                results.append((name, False, f"{type(e).__name__}: {e}"))

        ev = Event.search([('code', '=', 'HISPANO15')], limit=1)
        if not ev:
            ev = Event.create({'name': 'ZZ Evento test', 'code': 'HISPANO15',
                               'keywords': 'sociedad espanola',
                               'date_start': date(2026, 11, 24), 'date_end': date(2027, 1, 31)})
        n = [0]

        def mk(name='WhatsApp: 3589990001'):
            n[0] += 1
            return Partner.create({'name': name, 'mobile': f'+54935899{n[0]:05d}'})

        def c_entrada():
            p = mk()
            c = Contact.capture_inbound(p, "Hola! Quiero mi cupón del 15% - Código HISPANO15")
            assert c and c.state == 'active' and c.event_id == ev, c
            assert not ev.partner_tag_id or ev.partner_tag_id in p.category_id
            assert c.lead_id and 'HISPANO15' in c.lead_id.name, c.lead_id.name
            assert not ev.crm_tag_id or ev.crm_tag_id in c.lead_id.tag_ids
            assert c.lead_id.user_id.id != 18, "el lead no puede ir a Joaco"
            again = Contact.capture_inbound(p, "hispano 15")
            assert again == c and Contact.search_count([('partner_id', '=', p.id)]) == 1
            p2 = mk()
            c2 = Contact.capture_inbound(p2, "hola, vi el cupón en la Sociedad Española")
            assert c2 and c2.event_id == ev, "mención sin código"
            p3 = mk()
            assert not Contact.capture_inbound(p3, "hola, quiero precios de lavandina")
            p4 = mk()
            c4 = Contact.capture_inbound(p4, "Hola! Código HISPANO15, tengo un almacén y revendo")
            assert c4.state == 'wholesale', c4.state
            p.write({'name': 'Marta Gómez'})
            assert 'Marta Gómez' in c.lead_id.name, c.lead_id.name
            return "código, mención, sin duplicar, mayorista, lead renombrado con el nombre"
        case("Cupón evento: entrada día 0", c_entrada)

        def c_fechas():
            p = mk()
            c = Contact.register(p, ev)
            c.entry_date = datetime(2026, 11, 27, 15, 0)
            d = c.step_dates()
            assert d['A'] == date(2026, 11, 30) and d['B'] == date(2026, 12, 7), d
            assert d['C'] == date(2027, 1, 25), d          # 24/01 es domingo → lunes
            c.entry_date = datetime(2027, 1, 10, 15, 0)
            d = c.step_dates()
            assert d['C'] == date(2027, 1, 29) and d['A'] == date(2027, 1, 13) and d['B'] == date(2027, 1, 20), d
            c.entry_date = datetime(2027, 1, 28, 15, 0)
            d = c.step_dates()
            assert d['A'] is None and d['B'] is None, d
            return "A +3, B +10, C lunes 25/01; entrada de enero con tope 29/01"
        case("Cupón evento: fechas A/B/C", c_fechas)

        def c_envio():
            sent = []
            from ..services.tool_registry import ToolRegistry
            from ..services import tools  # noqa: F401
            tool = ToolRegistry.get('send_whatsapp_template')

            def fake(env=None, run=None, **kw):
                sent.append(kw)
                return {'ok': True}
            tool.execute = fake
            try:
                Cad = env['cristal.agent.cadence'].sudo()
                tpl = env['whatsapp.template'].sudo().search([('status', '=', 'approved')], limit=1)
                for cad in Cad.with_context(active_test=False).search([('step_code', 'in', ['A', 'B', 'C', 'D', 'E'])]):
                    cad.write({'whatsapp_template_id': tpl.id, 'active': True})
                p = mk('Lucía Pérez')
                c = Contact.register(p, ev)
                c.entry_date = fields.Datetime.now() - timedelta(days=4)
                from ..services import helpers
                orig_win = helpers.is_24h_window_open
                helpers.is_24h_window_open = lambda *a, **k: False
                try:
                    ok = c._run_due_step()
                    if c.step_dates().get('A') and c.step_dates()['A'] <= fields.Date.today():
                        assert ok and c.a_sent_at and sent[-1]['variables'][:2] == ['Lucía', 'HISPANO15'], (ok, c.last_note, sent)
                    assert not c._run_due_step(), "no manda dos veces"
                    p.set_agent_opt_out("test")
                    assert c.state == 'opted_out', c.state
                finally:
                    helpers.is_24h_window_open = orig_win
            finally:
                del tool.execute
            return f"A enviado con [nombre, código] ({len(sent)} envío simulado) · baja corta el circuito"
        case("Cupón evento: paso A y baja", c_envio)

        def c_compra():
            p = mk('Pedro Test')
            c = Contact.register(p, ev)
            c.a_sent_at = fields.Datetime.now() - timedelta(days=1)
            order = env['sale.order'].sudo().create({'partner_id': p.id})
            info = {'kind': 'web', 'order': order, 'partner': p, 'amount_untaxed': 25000.0,
                    'date': fields.Datetime.now(), 'ref': order.name}
            assert c._match_order(info)
            other = mk('Otro')
            assert not c._match_order(dict(info, partner=other))
            c._set_purchase(info)
            assert c.state == 'purchased' and c.purchase_step == 'A', (c.state, c.purchase_step)
            c.purchase_date = fields.Datetime.now() - timedelta(days=4)
            step, _d = c._due_step(fields.Date.today())
            assert step == 'D', step
            c.d_sent_at = fields.Datetime.now()
            c.purchase_date = fields.Datetime.now() - timedelta(days=31)
            step, _d = c._due_step(fields.Date.today())
            assert step == 'E', step
            c.e_sent_at = fields.Datetime.now()
            c._due_step(fields.Date.today())
            assert c.state == 'done', c.state
            return "venta vinculada (después de A) → D a los 3 días → E a los 30 → termina"
        case("Cupón evento: compra, D y E", c_compra)

        def c_tope_y_combo():
            p = mk('Tope Test')
            c = Contact.register(p, ev)
            c.write({'a_sent_at': fields.Datetime.now(), 'b_sent_at': fields.Datetime.now(),
                     'c_sent_at': fields.Datetime.now()})
            assert c.proactive_count == 3
            txt = Contact.combo_text()
            if txt:
                nums = [int(x.replace('.', '')) for x in re.findall(r'\$([\d.]+)', txt)]
                assert nums and nums[0] >= COUPON_MIN, txt
            return f"tope 3 mensajes · combo B: {txt or '(sin combos con stock en esta base)'}"
        case("Cupón evento: tope y combo de B", c_tope_y_combo)

        def c_guard():
            p = mk()
            c = Contact.register(p, ev)
            g = Contact.guard(p, "Hola! ¿En qué te ayudo?")
            assert g and g['guard'] == 'cupon_evento', g
            assert not Contact.guard(p, ev.coupon_message())
            Contact.note_outbound(p, ev.coupon_message() + " ¿Me decís tu nombre así te agendamos?")
            assert c.coupon_sent_at and c.name_asked
            q = mk('Sin cupón')
            g2 = Contact.guard(q, "Te paso el cupón HISPANO15 del 15%")
            assert g2 and g2['guard'] == 'cupon_no_pedido', g2
            lines = Contact.prompt_lines(p)
            assert lines and 'ya se lo mandaste' in ' '.join(lines), lines
            return "sin el cupón no sale · a quien no lo pidió no sale · marca cupón y nombre"
        case("Cupón evento: controles al enviar", c_guard)

        def c_sin_campana():
            out = []
            ev2 = Event.search([('code', '=', 'OULTON15')], limit=1)
            if ev2:
                ev2.write({'code_aliases': 'OUTLON15'})
                c2 = Contact.capture_inbound(mk(), "Hola! Quiero mi cupón del 15% - Código OUTLON15")
                assert c2 and c2.event_id == ev2, "OUTLON15 no se reconoce como OULTON15"
                out.append("OUTLON15 → OULTON15")
            from ..services.tool_registry import ToolRegistry
            from ..services import tools  # noqa: F401
            tool = ToolRegistry.get('send_whatsapp_template')
            sent = []
            tool.execute = lambda env=None, run=None, **kw: sent.append(kw) or {'ok': True}
            try:
                env['ir.config_parameter'].sudo().set_param('cristal_agent.event_coupon_followups', '0')
                p = mk('Sin Campaña')
                c = Contact.register(p, ev)
                c.write({'entry_date': fields.Datetime.now() - timedelta(days=4)})
                Contact.cron_event_coupons()
                assert not sent and not c.a_sent_at, "con la campaña apagada no sale nada"
            finally:
                del tool.execute
            out.append("cron sin envíos (solo mide compras)")
            return " · ".join(out)
        case("Cupón evento: sin campaña aparte", c_sin_campana)

        def c_medicion():
            ev.invalidate_recordset()
            ev._compute_kpis()
            return (f"leads {ev.kpi_leads}, usos {ev.kpi_uses}, facturación {_money(ev.kpi_revenue)}, "
                    f"costo regalo {_money(ev.kpi_gift_cost)}, por paso: {ev.kpi_by_step}")
        case("Cupón evento: medición", c_medicion)


class CristalAgentEventSimulation(models.AbstractModel):
    """v1.82.4 — Prueba de una conversación REAL con Claudio, sin mandar nada.

    Crea un contacto y su chat de WhatsApp de prueba, le "entra" cada mensaje como si lo
    escribiera una persona (mismo registro, mismo prompt, misma IA, mismas tools y mismos
    controles al enviar) y devuelve lo que Claudio habría contestado. Todo se revierte al
    final: no queda el contacto, ni la oportunidad, ni mensajes, y no sale ningún WhatsApp
    (context cristal_simulate: send_whatsapp y las tools que escriben hacia afuera solo
    anotan). Usa la API de Claude de verdad (cuesta como una conversación normal)."""
    _name = 'cristal.agent.event.simulation'
    _description = 'Cristal Agent — Simulación de conversación (cupones de eventos)'

    @api.model
    def simulate_chat(self, messages, profile_name=None, mobile=None):
        if isinstance(messages, str):
            messages = [messages]
        transcript, outbox = [], []

        class _Rollback(Exception):
            pass
        try:
            with self.env.cr.savepoint():
                self._simulate(messages, profile_name, mobile, transcript, outbox)
                raise _Rollback()
        except _Rollback:
            pass
        return transcript

    def _simulate(self, messages, profile_name, mobile, transcript, outbox):
        from ..services.claude_client import dispatch_agent_for_message
        env = self.env(user=1, context=dict(self.env.context, cristal_simulate=outbox,
                                            tz='America/Argentina/Cordoba'))
        config = env['cristal.agent.config'].sudo().get_active()
        account = env['whatsapp.account'].sudo().search([('name', '=', 'Cristal Mayorista')],
                                                        limit=1)
        mobile = mobile or '+5493589' + fields.Datetime.now().strftime('%H%M%S')
        partner = env['res.partner'].sudo().create({
            'name': f"WhatsApp: {mobile[-10:]}", 'mobile': mobile, 'phone': mobile})
        channel = env['discuss.channel'].sudo().create({
            'name': profile_name or partner.name, 'channel_type': 'whatsapp',
            'whatsapp_number': mobile, 'wa_account_id': account.id,
            'whatsapp_partner_id': partner.id,
            'channel_member_ids': [(0, 0, {'partner_id': partner.id})],
        })
        bot_pid = config.bot_partner_id.id if config.bot_partner_id else 2
        Memory = env['cristal.agent.memory'].sudo()
        for text in messages:
            msg = env['mail.message'].sudo().create({
                'model': 'discuss.channel', 'res_id': channel.id, 'body': text,
                'message_type': 'whatsapp_message', 'author_id': partner.id,
                'subtype_id': env.ref('mail.mt_comment').id})
            wa_msg = env['whatsapp.message'].sudo().new({
                'mobile_number': mobile, 'wa_account_id': account.id,
                'mail_message_id': msg.id, 'state': 'received', 'message_type': 'inbound',
                'body': text})
            memory = Memory.get_or_create(partner)
            memory.increment_received()
            memory.write({'client_type': config.detect_client_type(
                wa_account_id=account.id, partner=partner) or 'mayorista'})
            env['cristal.agent.event.contact'].sudo().capture_inbound(partner, text)
            try:
                partner.agent_capture_origin(text, first_message=len(transcript) == 0)
            except Exception:  # noqa: BLE001
                pass
            partner.write({'agent_last_inbound_at': fields.Datetime.now()})
            transcript.append({'from': 'cliente', 'text': text})
            start = len(outbox)
            dispatch_agent_for_message(env, wa_msg, partner, memory, text)
            for item in outbox[start:]:
                if item.get('tool') == 'send_whatsapp':
                    body = item['body'] or ''
                    if not item.get('internal'):
                        env['mail.message'].sudo().create({
                            'model': 'discuss.channel', 'res_id': channel.id, 'body': body,
                            'message_type': 'whatsapp_message', 'author_id': bot_pid,
                            'subtype_id': env.ref('mail.mt_comment').id})
                    text_out = re.sub(r'<br\s*/?>', '\n', body)
                    text_out = re.sub(r'</p>\s*<p>', '\n\n', text_out)
                    text_out = re.sub(r'<[^>]+>', '', text_out).strip()
                    transcript.append({'from': 'canal interno (Joaco)' if item.get('internal')
                                       else 'Claudio', 'text': text_out})
                else:
                    transcript.append({'from': f"[{item['tool']}]",
                                       'text': str(item.get('args'))[:600]})
            contact = env['cristal.agent.event.contact'].sudo().search(
                [('partner_id', '=', partner.id)], limit=1)
            transcript.append({'from': 'sistema', 'text': (
                f"contacto: {partner.name} · etiquetas: {', '.join(partner.category_id.mapped('name'))}"
                + (f" · cupón {contact.code} estado {contact.state}, cupón enviado: "
                   f"{'sí' if contact.coupon_sent_at else 'no'}, nombre pedido: "
                   f"{'sí' if contact.name_asked else 'no'}, oportunidad: {contact.lead_id.name}"
                   if contact else " · sin registro de cupón"))})


class ResPartnerEventCoupon(models.Model):
    _inherit = 'res.partner'

    agent_event_contact_ids = fields.One2many('cristal.agent.event.contact', 'partner_id',
                                              string="Cupones de eventos")

    def write(self, vals):
        res = super().write(vals)
        if 'name' in vals and not self.env.context.get('skip_event_rename'):
            contacts = self.env['cristal.agent.event.contact'].sudo().search(
                [('partner_id', 'in', self.ids)])
            if contacts:
                contacts.rename_leads()
        return res

    def set_agent_opt_out(self, reason, active=True):
        res = super().set_agent_opt_out(reason, active=active)
        if active:
            contacts = self.env['cristal.agent.event.contact'].sudo().search([
                ('partner_id', 'in', self.ids), ('state', 'in', ('active', 'purchased'))])
            if contacts:
                contacts.opt_out(reason)
        return res


class CristalAgentCadenceEvent(models.Model):
    _inherit = 'cristal.agent.cadence'

    trigger_event = fields.Selection(selection_add=[
        ('event_coupon', 'Cupón de evento (entrada)'),
        ('event_coupon_purchase', 'Compra con cupón de evento'),
    ], ondelete={'event_coupon': 'set default', 'event_coupon_purchase': 'set default'})
    step_code = fields.Char(
        string="Paso",
        help="Cupones de eventos: A (+3), B (+10), C (fin de enero), D (+3 de la compra), "
             "E (+30 de la compra). Lo usa el cron de cupones de eventos.")
