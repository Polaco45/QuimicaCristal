# -*- coding: utf-8 -*-
"""
v1.52 — Ciclo de vida del mayorista y "próxima mejor acción" (NBA).

Joaco (02/11/2026): "quiero que mi cliente mayorista sea totalmente autogestionado
por la IA". Primer bloque (fase 0 + fase 1 en seco del plan):

1. `res.partner.agent_lifecycle`: en qué etapa está cada mayorista, calculado todas
   las noches a partir de DATOS (pedidos, cotizaciones, mensajes), nunca de lo que
   diga el bot. Etapas: lead → calificado sin cotizar → cotizado sin comprar →
   cliente nuevo → activo → en riesgo → dormido → perdido / no contactar.
2. `res.partner.agent_origin_code`: de qué anuncio (o canal) vino el contacto. Se
   captura en el primer mensaje de WhatsApp (código corto tipo "MAY-SUAV" o la frase
   prellenada del anuncio) y se copia al origen del lead en el CRM.
3. `cristal.agent.nba`: una sola próxima acción por cliente y por semana, elegida por
   etapa y días transcurridos, con grupo de control. En modo "en seco" solo registra
   qué haría; en modo "real" agenda la actividad para Claudio (que ya ejecuta
   actividades con ventana, plantilla, horario y "No contactar" resueltos).

Nada de esto manda mensajes por sí mismo.
"""
import hashlib
import logging
import re
from datetime import timedelta
from statistics import median

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

LIFECYCLE = [
    ('lead', 'Lead (sin calificar)'),
    ('qualified_no_quote', 'Calificado sin cotizar'),
    ('quoted_no_order', 'Cotizado sin comprar'),
    ('new_customer', 'Cliente nuevo (1 compra)'),
    ('active', 'Activo'),
    ('at_risk', 'En riesgo'),
    ('dormant', 'Dormido'),
    ('lost', 'Perdido'),
    ('no_contact', 'No contactar'),
]

DEFAULT_CYCLE_DAYS = 30
NEW_CUSTOMER_DAYS = 60
LOST_DAYS = 180
GAP_DAYS = 7              # nunca dos acciones automáticas en 7 días
LIVE_CONVERSATION_DAYS = 3  # si escribió hace menos de 3 días, Claudio ya está hablando
CONVERSION_DAYS = 7

ORIGIN_CODE_RE = re.compile(r'\b([A-Z]{2,5}-[A-Z0-9]{2,8})\b')
# Prefijos válidos de los códigos de anuncio (param cristal_agent.origin_prefixes, separados
# por coma). Evita tomar "COVID-19" o "RE-X" como un anuncio.
DEFAULT_ORIGIN_PREFIXES = 'MAY,RUTA,CF,GAS,INST,PROMO,REF'
ORGANIC_CODE = 'ORGANICO'

# Catálogo de acciones: código → (etiqueta, canal, instrucción para Claudio).
ACTIONS = {
    'q_lista_pregunta': (
        "Calificado sin cotizar · día 3: lista + pregunta concreta", 'claudio',
        "Este cliente ya dijo de dónde es y qué hace, pero todavía no le armamos ninguna "
        "cotización. Si no tiene la lista, mandásela (generate_pricelist_pdf). Preguntale "
        "UNA cosa concreta: qué producto mueve más y cuántos litros por mes, y ofrecé "
        "cotizarle 2 productos para que vea el precio final con envío."),
    'q_combo': (
        "Calificado sin cotizar · día 10: Combo Emprendedor", 'claudio',
        "Pasaron 10 días desde que lo calificamos y no cotizó nada. Ofrecele el Combo "
        "Emprendedor del contexto (si está activo) como punto de partida, con el total y "
        "qué incluye. Si no hay combo activo, ofrecé cotizar los 3 productos que más "
        "rotan en su rubro."),
    'q_oferta_mes': (
        "Calificado sin cotizar · día 30: oferta vigente", 'claudio',
        "Un mes sin cotizar. Buscá la oferta vigente (search_offers only_proactive=true) y "
        "pasásela en una línea con precio. Si no hay oferta, preguntá si sigue interesado "
        "o si prefiere que no le escribamos más (mark_opt_out si dice que no)."),
    'c_objecion': (
        "Cotizado sin comprar · día 15: objeción", 'claudio',
        "Le mandamos una cotización hace 15 días y no la cerró (ya se le hizo el "
        "seguimiento de los días 1 y 3). Preguntale directo qué lo frenó: precio, cantidad, "
        "entrega o forma de pago, y ofrecé ajustar la cotización (menos litros, retiro en "
        "planta sin mínimo, otro producto). No repitas el total de memoria: mirá la "
        "cotización con search_orders."),
    'c_promo': (
        "Cotizado sin comprar · día 30: promo o envío", 'claudio',
        "Un mes desde la cotización sin compra. Pasale la oferta vigente (search_offers) o "
        "recordale que retirando en planta no hay mínimo. Una línea, sin insistir."),
    'c_ultima': (
        "Cotizado sin comprar · día 60: último mensaje", 'claudio',
        "Dos meses sin respuesta. Último mensaje, cordial: que cuando necesite productos "
        "nos escriba y le armamos la cotización al precio del día. Si no responde, no se "
        "lo vuelve a escribir (lo marca el sistema)."),
    'n_chequeo': (
        "Cliente nuevo · día 3: chequeo post-compra", 'claudio',
        "Hizo su primera compra hace 3 días. Preguntale cómo le fueron los productos y "
        "cómo viene la venta. Guardá lo que diga con update_observation."),
    'n_producto_top': (
        "Cliente nuevo · día 10: producto que más rota", 'claudio',
        "Preguntale cuál de los productos que llevó le está rotando mejor; guardalo con "
        "update_observation (sirve para la reposición). Si menciona uno que no llevó, "
        "cotizáselo."),
    'n_segunda_compra': (
        "Cliente nuevo · día 20: segunda compra", 'claudio',
        "Compró una vez hace 20 días. Ofrecé reponer lo que llevó (search_orders te da el "
        "pedido) y sumá UN complemento (suggest_products). Si es de la ruta, pasale la "
        "próxima fecha del camión (get_route_info)."),
    'n_reposicion': (
        "Cliente nuevo · día 45 sin recompra: reposición", 'claudio',
        "45 días desde su única compra. Preguntale si ya se le terminó y ofrecé reponer "
        "lo mismo con la oferta vigente si aplica."),
    'a_reposicion': (
        "Activo · le toca reponer", 'claudio',
        "Cliente que compra seguido y ya pasó su intervalo habitual. Ofrecé reponer sus "
        "productos habituales (search_orders) y sumá UN complemento con suggest_products. "
        "Corto, como quien avisa."),
    'r_reactivacion_1': (
        "En riesgo · reactivación 1: te extrañamos", 'claudio',
        "Lleva más de 1,5 ciclos sin comprar. Mensaje corto: que no lo vimos hace un tiempo, "
        "preguntá si cambió algo (proveedor, precio, rubro) y ofrecé cotizar al precio de "
        "hoy. Guardá el motivo con update_observation."),
    'r_reactivacion_2': (
        "En riesgo · reactivación 2: motivo concreto", 'claudio',
        "Segundo intento, dos semanas después del primero. Pasale un motivo concreto para "
        "volver: la oferta vigente (search_offers) o el producto que más llevaba a precio de "
        "hoy. Si dice que no vende más, mark_opt_out."),
    'd_reactivacion_3': (
        "Dormido · reactivación 3: último aviso", 'claudio',
        "Más de 3 ciclos sin comprar. Último mensaje: que la puerta queda abierta y que "
        "cuando quiera le cotizamos al precio del día. Sin oferta agresiva, sin insistir."),
    'd_visita': (
        "Dormido · visita de la vendedora", 'visit',
        "Cliente dormido de Río Cuarto / Las Higueras con ticket alto: conviene una visita "
        "presencial en vez de otro mensaje."),
}
ACTION_SELECTION = [(k, v[0]) for k, v in ACTIONS.items()]
# Orden de prioridad cuando hay más candidatos que cupo diario: primero la plata parada
# y fresca (cotizaciones recientes), último lo que lleva meses frío.
PRIORITY = ['c_objecion', 'c_promo', 'n_chequeo', 'n_producto_top', 'n_segunda_compra',
            'a_reposicion', 'n_reposicion', 'q_lista_pregunta', 'q_combo', 'r_reactivacion_1',
            'r_reactivacion_2', 'c_ultima', 'q_oferta_mes', 'd_reactivacion_3', 'd_visita']
# Estados que cuentan como "se lo tocó" (en seco solo es un registro).
TOUCH_STATES = ('holdout', 'planned', 'done')


def _first_name(partner):
    name = (partner.name or '').strip()
    if ',' in name:
        name = name.split(',', 1)[1].strip()
    return (name.split() or [''])[0]


class ResPartnerLifecycle(models.Model):
    _inherit = 'res.partner'

    agent_lifecycle = fields.Selection(
        LIFECYCLE, string="Etapa (ciclo de vida)", index=True, copy=False,
        help="Calculada todas las noches a partir de pedidos, cotizaciones y mensajes. "
             "No la cambia el bot ni se edita a mano.")
    agent_lifecycle_date = fields.Date(string="En esta etapa desde", copy=False)
    agent_lifecycle_reason = fields.Char(string="Por qué está en esta etapa", copy=False)
    agent_lifecycle_computed_at = fields.Datetime(string="Etapa calculada el", copy=False)
    agent_origin_code = fields.Char(
        string="Origen (código del anuncio)", index=True, copy=False,
        help="Código corto del anuncio o canal con el que llegó (ej. MAY-SUAV). "
             "ORGANICO = escribió sin venir de un anuncio conocido.")
    agent_origin_date = fields.Datetime(string="Origen captado el", copy=False)
    agent_origin_text = fields.Char(string="Primer mensaje", copy=False)
    agent_nba_ids = fields.One2many('cristal.agent.nba', 'partner_id',
                                    string="Acciones automáticas")
    agent_nba_count = fields.Integer(compute='_compute_agent_nba_count')
    # v1.56 — Referidos: crédito pendiente (%) que se aplica solo en la próxima cotización.
    agent_referral_credit_pct = fields.Float(
        string="Crédito por referido (%)", copy=False,
        help="Descuento pendiente por recomendar (o por venir recomendado). Lo aplica "
             "create_sale_order y se consume al confirmar el pedido.")
    agent_referral_credit_note = fields.Char(string="Motivo del crédito", copy=False)
    agent_referral_rewarded = fields.Boolean(
        string="Referido ya premiado", copy=False,
        help="Quien lo recomendó ya recibió su crédito por la primera compra de este cliente.")
    agent_referral_rewarded_date = fields.Date(string="Premiado el", copy=False)

    def agent_grant_referral_credit(self, pct, note):
        """Deja (o sube a) `pct` el crédito por referido, con su motivo."""
        for p in self.sudo():
            if pct > (p.agent_referral_credit_pct or 0.0):
                p.write({'agent_referral_credit_pct': pct,
                         'agent_referral_credit_note': (note or '')[:250]})
                p.append_agent_observation(f"🎁 Crédito por referido {pct:g}%: {note}")

    def _compute_agent_nba_count(self):
        counts = {p.id: n for p, n in self.env['cristal.agent.nba']._read_group(
            [('partner_id', 'in', self.ids)], ['partner_id'], ['__count'])}
        for p in self:
            p.agent_nba_count = counts.get(p.id, 0)

    # ───────────────────────── Origen / atribución ─────────────────────────
    @api.model
    def _agent_origin_phrases(self):
        """[(código, frase)] de los anuncios. Parámetro cristal_agent.origin_phrases: una
        línea por anuncio, "CODIGO | frase prellenada". Si no está, se usan las frases de
        cristal_minorista.ad_messages (separadas por |) con códigos AD1, AD2…"""
        Param = self.env['ir.config_parameter'].sudo()
        out = []
        raw = Param.get_param('cristal_agent.origin_phrases') or ''
        for line in raw.splitlines():
            if '|' in line:
                code, phrase = line.split('|', 1)
                if code.strip() and phrase.strip():
                    out.append((code.strip().upper()[:20], phrase.strip()))
        if not out:
            phrases = [p.strip() for p in (Param.get_param('cristal_minorista.ad_messages')
                                           or '').split('|') if p.strip()]
            out = [(f"AD{i}", p) for i, p in enumerate(phrases, start=1)]
        return out

    def agent_capture_origin(self, text, first_message=False, when=None):
        """Guarda el origen del contacto a partir de su mensaje. Solo la primera vez.
        Devuelve el código guardado o False."""
        self.ensure_one()
        if self.agent_origin_code:
            return False
        text = (text or '').strip()
        code = False
        prefixes = {p.strip().upper() for p in (self.env['ir.config_parameter'].sudo().get_param(
            'cristal_agent.origin_prefixes') or DEFAULT_ORIGIN_PREFIXES).split(',') if p.strip()}
        for m in ORIGIN_CODE_RE.finditer(text.upper()):
            if m.group(1).split('-', 1)[0] in prefixes:
                code = m.group(1)
                break
        if not code:
            low = text.lower()
            for c, phrase in self._agent_origin_phrases():
                if phrase.lower() in low:
                    code = c
                    break
        if not code and first_message and text:
            code = ORGANIC_CODE
        if not code:
            return False
        self.sudo().write({'agent_origin_code': code,
                           'agent_origin_date': when or fields.Datetime.now(),
                           'agent_origin_text': text[:200]})
        return code

    def agent_origin_utm_source(self):
        """utm.source del código de origen (se crea si no existe) o False."""
        self.ensure_one()
        if not self.agent_origin_code or 'utm.source' not in self.env:
            return False
        Source = self.env['utm.source'].sudo()
        src = Source.search([('name', '=', self.agent_origin_code)], limit=1)
        return src or Source.create({'name': self.agent_origin_code})

    def action_view_agent_nba(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': "Acciones automáticas",
            'res_model': 'cristal.agent.nba', 'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }


class CristalAgentLifecycle(models.AbstractModel):
    _name = 'cristal.agent.lifecycle'
    _description = "Cristal Agent — Ciclo de vida del mayorista"

    # ───────────────────────── Universo ─────────────────────────
    @api.model
    def mayorista_partners(self):
        """Mayoristas (etiqueta) + contactos con memoria mayorista. Sin internos."""
        Partner = self.env['res.partner'].sudo()
        tag = self.env['res.partner.category'].sudo().search([('name', '=', 'Mayorista')],
                                                             limit=1)
        partners = Partner.search([('category_id', 'in', tag.ids)]) if tag else Partner
        memories = self.env['cristal.agent.memory'].sudo().search(
            [('client_type', '=', 'mayorista'), ('partner_id.active', '=', True)])
        partners |= memories.mapped('partner_id')
        config = self.env['cristal.agent.config'].sudo().get_active()
        if config:
            partners -= config.owner_partner_id | config.bot_partner_id \
                | config.owner_whatsapp_partner_id
        return partners.filtered(lambda p: not p.user_ids)   # usuarios internos afuera

    # ───────────────────────── Datos por partner ─────────────────────────
    @api.model
    def gather(self, partners, today):
        """{partner_id: stats} con todo lo que necesita la clasificación y la NBA."""
        SO = self.env['sale.order'].sudo()
        stats = {p.id: {'orders': 0, 'first_order': None, 'last_order': None,
                        'quotes': 0, 'last_quote': None, 'cycle': None}
                 for p in partners}
        for partner, dmax, dmin, count in SO._read_group(
                [('partner_id', 'in', partners.ids), ('state', 'in', ('sale', 'done'))],
                ['partner_id'], ['date_order:max', 'date_order:min', '__count']):
            s = stats[partner.id]
            s.update(orders=count, last_order=dmax.date() if dmax else None,
                     first_order=dmin.date() if dmin else None)
        for partner, cmax, count in SO._read_group(
                [('partner_id', 'in', partners.ids), ('state', 'in', ('draft', 'sent', 'cancel'))],
                ['partner_id'], ['create_date:max', '__count']):
            s = stats[partner.id]
            s.update(quotes=count, last_quote=cmax.date() if cmax else None)
        # Ciclo de recompra: el de cristal_minorista si está; si no, mediana de gaps.
        config = self.env['cristal.agent.config'].sudo().get_active()
        default_cycle = (config.lifecycle_default_cycle_days if config else 0) or DEFAULT_CYCLE_DAYS
        has_minorista = 'cristal_cycle_days' in partners._fields
        need_median = []
        for p in partners:
            s = stats[p.id]
            cyc = p.cristal_cycle_days if has_minorista else 0
            if cyc and cyc > 0 and s['orders'] >= 2:
                s['cycle'] = max(7, int(cyc))
            elif s['orders'] >= 3:
                need_median.append(p.id)
            else:
                s['cycle'] = default_cycle
        if need_median:
            dates = {}
            for o in SO.search_read([('partner_id', 'in', need_median),
                                     ('state', 'in', ('sale', 'done'))],
                                    ['partner_id', 'date_order'], order='date_order asc'):
                if o['date_order']:
                    dates.setdefault(o['partner_id'][0], []).append(o['date_order'].date())
            for pid in need_median:
                ds = sorted(set(dates.get(pid, [])))
                gaps = [(b - a).days for a, b in zip(ds, ds[1:]) if (b - a).days > 0]
                stats[pid]['cycle'] = max(7, int(median(gaps))) if gaps else default_cycle
        return stats

    @api.model
    def classify(self, partner, s, today):
        """(etapa, motivo) de un partner con sus stats."""
        if partner.agent_opt_out:
            return 'no_contact', partner.agent_opt_out_reason or "pidió no recibir propuestas"
        cycle = s['cycle'] or DEFAULT_CYCLE_DAYS
        if s['orders']:
            d = (today - s['last_order']).days
            if d > LOST_DAYS:
                return 'lost', f"{d} días sin comprar"
            if s['orders'] == 1 and (today - s['first_order']).days <= NEW_CUSTOMER_DAYS:
                return 'new_customer', f"primera compra hace {d} días"
            if d > max(3 * cycle, 90):
                return 'dormant', f"{d} días sin comprar (ciclo {cycle})"
            if d > 1.5 * cycle:
                return 'at_risk', f"{d} días sin comprar (ciclo {cycle})"
            return 'active', f"{s['orders']} pedidos, último hace {d} días (ciclo {cycle})"
        # Nunca compró.
        last_seen = partner.agent_last_inbound_at or partner.create_date
        idle = (today - last_seen.date()).days if last_seen else 0
        if s['quotes']:
            if idle > LOST_DAYS and (today - s['last_quote']).days > LOST_DAYS:
                return 'lost', f"cotizado hace {(today - s['last_quote']).days} días, sin señales"
            return 'quoted_no_order', f"{s['quotes']} cotización(es), última hace " \
                                      f"{(today - s['last_quote']).days} días"
        if idle > LOST_DAYS:
            return 'lost', f"{idle} días sin escribir ni cotizar"
        # Calificado = ya sabemos de dónde es (ciudad cargada) o el bot lo marcó calificado.
        qualified = bool(partner.city) \
            or partner.agent_strategy_phase in ('phase_1_qualified', 'phase_2_post_sample')
        if qualified:
            since = partner.agent_phase_started_at or partner.create_date
            return 'qualified_no_quote', f"calificado hace {(today - since.date()).days} días, sin cotización"
        return 'lead', "sin localidad ni cotización"

    @api.model
    def recompute(self, partners=None, today=None):
        """Recalcula la etapa de todos (o de `partners`). Devuelve ({etapa: cantidad}, stats)."""
        from ..services.helpers import now_ar
        today = today or now_ar(self.env).date()
        partners = partners if partners is not None else self.mayorista_partners()
        stats = self.gather(partners, today)
        counts = {}
        now = fields.Datetime.now()
        for p in partners:
            state, reason = self.classify(p, stats[p.id], today)
            counts[state] = counts.get(state, 0) + 1
            vals = {'agent_lifecycle_computed_at': now}
            if p.agent_lifecycle != state:
                vals.update(agent_lifecycle=state, agent_lifecycle_date=today)
            if (p.agent_lifecycle_reason or '') != reason:
                vals['agent_lifecycle_reason'] = reason[:200]
            p.sudo().with_context(tracking_disable=True).write(vals)
        _logger.info("🧭 Ciclo de vida recalculado: %s", counts)
        return counts, stats

    @api.model
    def cron_lifecycle_daily(self):
        """Diario: etapas + conversiones de acciones previas + próxima mejor acción."""
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config or (config.lifecycle_mode or 'off') == 'off':
            _logger.info("cron_lifecycle_daily: modo off, salgo")
            return False
        from ..services.helpers import now_ar
        today = now_ar(self.env).date()
        partners = self.mayorista_partners()
        counts, stats = self.recompute(partners, today)
        NBA = self.env['cristal.agent.nba'].sudo()
        NBA.mark_conversions(today)
        planned = NBA.plan(partners, stats, today, config)
        return {'lifecycle': counts, 'planned': len(planned)}


class CristalAgentNBA(models.Model):
    _name = 'cristal.agent.nba'
    _description = "Cristal Agent — Próxima mejor acción"
    _order = 'date desc, id desc'
    _rec_name = 'action_label'

    partner_id = fields.Many2one('res.partner', string="Cliente", required=True, index=True,
                                 ondelete='cascade')
    date = fields.Date(string="Fecha", required=True, index=True, default=fields.Date.today)
    lifecycle = fields.Selection(LIFECYCLE, string="Etapa", index=True)
    action_code = fields.Selection(ACTION_SELECTION, string="Acción", required=True, index=True)
    action_label = fields.Char(string="Acción (texto)")
    channel = fields.Selection([('claudio', 'Claudio (WhatsApp)'), ('visit', 'Visita'),
                                ('none', 'Ninguna')], string="Canal", default='claudio')
    reason = fields.Text(string="Motivo")
    state = fields.Selection([
        ('dry_run', 'En seco (no se hizo)'),
        ('holdout', 'Grupo de control'),
        ('planned', 'Agendada a Claudio'),
        ('done', 'Hecha'),
        ('skipped', 'Descartada'),
    ], string="Estado", required=True, default='dry_run', index=True)
    activity_id = fields.Many2one('mail.activity', string="Actividad")
    converted = fields.Boolean(string="Compró después", index=True,
                               help="Pedido confirmado dentro de los 7 días siguientes.")
    converted_order_id = fields.Many2one('sale.order', string="Pedido")
    converted_amount = fields.Float(string="Monto (sin IVA)", digits=(12, 0))
    origin_code = fields.Char(related='partner_id.agent_origin_code', store=True,
                              string="Origen")
    zone = fields.Selection(related='partner_id.agent_zone', store=True, string="Zona")

    # ───────────────────────── Elección de la acción ─────────────────────────
    @api.model
    def _candidate(self, partner, s, today, config):
        """(código, motivo) o None para este partner según etapa y días."""
        lc = partner.agent_lifecycle
        last = {}
        for n in self.search([('partner_id', '=', partner.id), ('state', 'in', TOUCH_STATES)]):
            last.setdefault(n.action_code, n.date)   # ordenado desc: la más reciente
        cycle = s['cycle'] or DEFAULT_CYCLE_DAYS

        def once(code, reason):
            return None if code in last else (code, reason)

        if lc == 'qualified_no_quote':
            since = partner.agent_phase_started_at or partner.create_date
            days = (today - since.date()).days
            if days >= 30:
                offers = self.env['cristal.agent.offer'].sudo().search_for_agent(
                    only_proactive=True, limit=1)
                if offers:
                    return once('q_oferta_mes', f"{days} días calificado, sin cotizar")
                return None
            if days >= 10:
                return once('q_combo', f"{days} días calificado, sin cotizar")
            if days >= 3:
                return once('q_lista_pregunta', f"{days} días calificado, sin cotizar")
        elif lc == 'quoted_no_order':
            days = (today - s['last_quote']).days
            if days >= 60:
                return once('c_ultima', f"{days} días desde la última cotización")
            if days >= 30:
                return once('c_promo', f"{days} días desde la última cotización")
            if days >= 15:
                return once('c_objecion', f"{days} días desde la última cotización")
        elif lc == 'new_customer':
            days = (today - s['first_order']).days
            if days >= 45:
                return once('n_reposicion', f"{days} días desde la primera compra, sin recompra")
            if days >= 20:
                return once('n_segunda_compra', f"{days} días desde la primera compra")
            if days >= 10:
                return once('n_producto_top', f"{days} días desde la primera compra")
            if days >= 3:
                return once('n_chequeo', f"{days} días desde la primera compra")
        elif lc == 'active':
            days = (today - s['last_order']).days
            if days >= cycle:
                prev = last.get('a_reposicion')
                if not prev or (today - prev).days >= cycle:
                    return ('a_reposicion', f"{days} días desde el último pedido (ciclo {cycle})")
        elif lc == 'at_risk':
            r1 = last.get('r_reactivacion_1')
            if not r1:
                return ('r_reactivacion_1', f"{(today - s['last_order']).days} días sin comprar")
            if 'r_reactivacion_2' not in last and (today - r1).days >= 14:
                return ('r_reactivacion_2', "sin respuesta a la reactivación 1")
        elif lc == 'dormant':
            r3 = last.get('d_reactivacion_3')
            if not r3:
                return ('d_reactivacion_3', f"{(today - s['last_order']).days} días sin comprar")
            if 'd_visita' not in last and (today - r3).days >= 14 \
                    and partner.agent_zone in ('rio_cuarto', 'las_higueras'):
                ticket = getattr(partner, 'cristal_avg_ticket', 0.0) or 0.0
                if ticket >= (config.lifecycle_visit_min_ticket or 0.0):
                    return ('d_visita', f"dormido, ticket promedio ${ticket:,.0f}")
        return None

    @api.model
    def _blocked_reason(self, partner, today):
        """Por qué NO se lo toca hoy (None = se puede)."""
        if partner.agent_opt_out:
            return "no contactar"
        if not (partner.mobile or partner.phone):
            return "sin teléfono"
        if partner.parent_id and partner.parent_id.is_company and partner.parent_id.agent_lifecycle:
            return "contacto de una empresa que ya se gestiona"
        since = today - timedelta(days=GAP_DAYS)
        if self.search_count([('partner_id', '=', partner.id), ('date', '>', since),
                              ('state', 'in', TOUCH_STATES)]):
            return "ya tuvo una acción esta semana"
        if self.search_count([('partner_id', '=', partner.id), ('date', '=', today)]):
            return "ya se evaluó hoy"
        if partner.agent_last_inbound_at and \
                partner.agent_last_inbound_at.date() > today - timedelta(days=LIVE_CONVERSATION_DAYS):
            return "está conversando con Claudio"
        mem = partner.agent_memory_id
        if mem and mem.is_takeover_active():
            return "intervención humana activa"
        if partner.agent_reorder_reminder_date and partner.agent_reorder_reminder_date > since:
            return "ya tiene recordatorio de recompra"
        Run = self.env['cristal.agent.run'].sudo()
        if Run.search_count([('partner_id', '=', partner.id), ('trigger', '=', 'cron_cadence'),
                             ('create_date', '>', fields.Datetime.to_datetime(since))]):
            return "ya tuvo una cadencia esta semana"
        config = self.env['cristal.agent.config'].sudo().get_active()
        if config and config.bot_user_id and self.env['mail.activity'].sudo().search_count([
                ('user_id', '=', config.bot_user_id.id), ('res_model', '=', 'res.partner'),
                ('res_id', '=', partner.id)]):
            return "Claudio ya tiene una actividad pendiente"
        if 'cristal.cobranza.action' in self.env and self.env['cristal.cobranza.action'].sudo(
        ).search_count([('partner_id', '=', partner.id),
                        ('create_date', '>', fields.Datetime.to_datetime(since))]):
            return "en gestión de cobranza"
        if 'cristal.fid.touch' in self.env and self.env['cristal.fid.touch'].sudo().search_count([
                ('partner_id', '=', partner.id), ('state', '=', 'sent'),
                ('date', '>', fields.Datetime.to_datetime(since))]):
            return "ya recibió un mensaje de fidelización"
        return None

    @api.model
    def _in_holdout(self, partner, code, pct):
        h = int(hashlib.md5(f"{partner.id}:{code}".encode()).hexdigest()[:8], 16)
        return h % 100 < (pct or 0)

    @api.model
    def plan(self, partners, stats, today, config, limit=None):
        """Elige y registra la próxima acción de cada partner que lo amerite. Devuelve los
        registros creados. Respeta el cupo diario y el modo (en seco / real)."""
        mode = config.lifecycle_mode or 'dry_run'
        cap = limit if limit is not None else (config.lifecycle_daily_cap or 30)
        cands = []
        for p in partners:
            if p.agent_lifecycle in (False, 'lead', 'lost', 'no_contact'):
                continue
            c = self._candidate(p, stats[p.id], today, config)
            if not c:
                continue
            if self._blocked_reason(p, today):
                continue
            cands.append((p, c[0], c[1]))
        cands.sort(key=lambda x: PRIORITY.index(x[1]) if x[1] in PRIORITY else 99)
        # En modo real solo se ejecutan las acciones habilitadas (config); el resto queda
        # en seco. Vacío = todas. Se aceptan códigos o prefijos ("c_" = las de cotizados).
        allowed = [a.strip() for a in (config.lifecycle_live_actions or '').split(',') if a.strip()]

        def live_for(code):
            return mode == 'live' and (not allowed or any(code == a or code.startswith(a)
                                                          for a in allowed))
        created = self.browse()
        n_planned = 0
        for p, code, reason in cands:
            label, channel, instr = ACTIONS[code]
            vals = {'partner_id': p.id, 'date': today, 'lifecycle': p.agent_lifecycle,
                    'action_code': code, 'action_label': label, 'channel': channel,
                    'reason': reason, 'state': 'dry_run'}
            is_live = live_for(code)
            if is_live and n_planned >= cap:
                continue   # hoy no entra en el cupo; se vuelve a evaluar mañana
            if is_live and self._in_holdout(p, code, config.lifecycle_holdout_pct):
                vals['state'] = 'holdout'
            elif is_live:
                vals['state'] = 'planned'
                act = self._schedule(p, code, label, channel, instr, reason, config, today)
                if act:
                    vals['activity_id'] = act.id
                    n_planned += 1
                else:
                    vals['state'] = 'dry_run'   # sin bot o sin responsable de visitas
            created |= self.create(vals)
        from collections import Counter
        _logger.info("🧭 NBA: %s acciones (%s) — modo %s", len(created),
                     dict(Counter(created.mapped('state'))), mode)
        return created

    @api.model
    def _schedule(self, partner, code, label, channel, instr, reason, config, today):
        if channel == 'visit':
            user = config.lifecycle_visit_user_id
            if not user:
                return False
            return partner.activity_schedule(
                'mail.mail_activity_data_todo', date_deadline=today + timedelta(days=2),
                summary=f"Visita sugerida: {partner.name}", user_id=user.id,
                note=f"{instr} Motivo: {reason}.")
        if not config.bot_user_id:
            return False
        return partner.activity_schedule(
            'mail.mail_activity_data_todo', date_deadline=today, user_id=config.bot_user_id.id,
            summary=f"[NBA] {label}",
            note=(f"{instr}\n\nMotivo: {reason}. Nombre de pila: {_first_name(partner) or '—'}. "
                  f"Un solo mensaje, corto. Si contesta, seguís la charla normal. "
                  f"Con la ventana de 24 h cerrada, send_whatsapp sale por la plantilla sola."))

    # ───────────────────────── Resultado ─────────────────────────
    @api.model
    def mark_conversions(self, today):
        """Cierra las actividades hechas y marca las acciones que terminaron en pedido."""
        since = today - timedelta(days=21)
        open_ = self.search([('date', '>=', since), ('converted', '=', False),
                             ('state', 'in', ('dry_run', 'holdout', 'planned', 'done'))])
        SO = self.env['sale.order'].sudo()
        for n in open_:
            if n.state == 'planned' and n.activity_id and \
                    (not n.activity_id.exists() or not n.activity_id.active):
                n.state = 'done'
            order = SO.search([('partner_id', '=', n.partner_id.id),
                               ('state', 'in', ('sale', 'done')),
                               ('date_order', '>=', fields.Datetime.to_datetime(n.date)
                                - timedelta(hours=12)),   # la fecha es AR, el campo es UTC
                               ('date_order', '<', fields.Datetime.to_datetime(
                                   n.date + timedelta(days=CONVERSION_DAYS + 1)))],
                              order='date_order asc', limit=1)
            if order:
                n.write({'converted': True, 'converted_order_id': order.id,
                         'converted_amount': order.amount_untaxed})
        return True

    @api.model
    def summary(self, start, end):
        """Números para el informe semanal: por estado, conversión y control."""
        recs = self.search([('date', '>=', start), ('date', '<', end)])
        reached = recs.filtered(lambda n: n.state in ('planned', 'done'))
        dry = recs.filtered(lambda n: n.state == 'dry_run')
        hold = recs.filtered(lambda n: n.state == 'holdout')

        def rate(rs):
            return (100.0 * len(rs.filtered('converted')) / len(rs)) if rs else 0.0
        by_action = {}
        for n in recs:
            by_action.setdefault(n.action_label, [0, 0])
            by_action[n.action_label][0] += 1
            by_action[n.action_label][1] += 1 if n.converted else 0
        return {'total': len(recs), 'reached': len(reached), 'dry': len(dry),
                'holdout': len(hold), 'rate_reached': rate(reached), 'rate_dry': rate(dry),
                'rate_holdout': rate(hold), 'by_action': by_action,
                'amount': sum(reached.mapped('converted_amount'))}
