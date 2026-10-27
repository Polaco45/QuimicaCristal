# -*- coding: utf-8 -*-
"""
Log auditable de cada ejecución del agente.

Cada vez que el agente se activa (mensaje WA, cron, comando manual), se crea
un AgentRun que registra:
- Qué disparador lo activó
- Qué partner está involucrado
- Qué mensaje recibió (si aplica)
- Qué tools llamó y con qué argumentos
- Qué tool_results recibió
- Qué respuesta final generó
- Cuántos tokens consumió y cuánto costó
- Cuánto tardó
- Si terminó OK o con error

Esto permite auditar al agente, debuggearlo, y eventualmente entrenarlo
identificando patrones de éxito/falla.
"""
import json
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class CristalAgentRun(models.Model):
    _name = 'cristal.agent.run'
    _description = "Cristal Agent — Ejecución auditada"
    _order = 'create_date desc'
    _rec_name = 'display_name'

    # ─────────── Identificación ───────────
    display_name = fields.Char(
        string="Nombre",
        compute='_compute_display_name',
        store=True,
    )

    trigger = fields.Selection([
        ('whatsapp_message', 'Mensaje WhatsApp entrante'),
        ('cron_cadence', 'Cron — Cadencia comercial'),
        ('cron_levels', 'Cron — Recálculo de niveles'),
        ('cron_churn', 'Cron — Detección de churn'),
        ('cron_recovery', 'Cron — Recuperación 45 días'),
        ('cron_rituals', 'Cron — Rituales de fidelización'),
        ('joaco_command', 'Comando de Joaco en canal interno'),
        ('manual', 'Disparo manual (wizard)'),
        ('webhook', 'Webhook externo'),
        ('other', 'Otro'),
    ], string="Disparador", required=True, default='other')

    state = fields.Selection([
        ('running', 'En ejecución'),
        ('done', 'Completado'),
        ('error', 'Error'),
        ('timeout', 'Timeout'),
        ('cancelled', 'Cancelado'),
    ], string="Estado", default='running', required=True)

    # ─────────── Contexto ───────────
    partner_id = fields.Many2one(
        'res.partner',
        string="Cliente",
        index=True,
    )
    channel_id = fields.Many2one(
        'discuss.channel',
        string="Canal Discuss",
    )
    incoming_message_id = fields.Many2one(
        'mail.message',
        string="Mensaje entrante",
        help="Mail.message que disparó esta ejecución (si aplica).",
    )
    incoming_text = fields.Text(string="Texto del mensaje entrante (limpio)")

    # ─────────── Resultado ───────────
    final_response = fields.Text(
        string="Respuesta final del agente",
        help="Texto que Claude generó como respuesta final (después de todos los tool calls).",
    )
    error_message = fields.Text(string="Error (si lo hubo)")

    # ─────────── Métricas ───────────
    iterations = fields.Integer(
        string="Iteraciones tool_use",
        default=0,
        help="Cantidad de ciclos tool_use → tool_result que ejecutó Claude.",
    )
    total_tool_calls = fields.Integer(
        string="Tool calls totales",
        default=0,
    )
    input_tokens = fields.Integer(string="Tokens input acumulados")
    output_tokens = fields.Integer(string="Tokens output acumulados")
    cache_creation_input_tokens = fields.Integer(string="Tokens cache write")
    cache_read_input_tokens = fields.Integer(string="Tokens cache read")
    # v1.42 — la caché de la conversación de cada cliente dura 5 min (1,25x) y la
    # parte fija 1 h (2x). Lo de 5 min se guarda aparte; el resto es de 1 h.
    cache_creation_5m_tokens = fields.Integer(string="Tokens cache write (5 min)")
    api_cost_usd = fields.Float(
        string="Costo calculado por llamada", digits=(10, 6),
        help="Suma del costo de cada llamada con los precios del modelo que la "
             "atendió (en una corrida puede pasar de Haiku a Sonnet).")
    model_reason = fields.Char(string="Por qué este modelo")
    model_used = fields.Char(
        string="Modelo usado",
        help="Modelo de Claude con el que se corrió este run. Determina los "
             "precios que usa el cálculo de costo.",
    )
    cost_usd = fields.Float(
        string="Costo USD",
        digits=(10, 6),
        compute='_compute_cost',
        store=True,
    )
    duration_seconds = fields.Float(
        string="Duración (segundos)",
        digits=(10, 2),
    )

    # ─────────── Trazas detalladas ───────────
    tool_calls_log = fields.Text(
        string="Log de tool calls (JSON)",
        help="JSON con cada tool call: nombre, input, output, duración.",
    )
    full_messages_log = fields.Text(
        string="Log completo (JSON)",
        help="Conversación completa con Claude (todos los messages enviados y recibidos). "
             "Útil para debug profundo.",
    )

    # ─────────── Computeds ───────────
    @api.depends('trigger', 'partner_id', 'create_date')
    def _compute_display_name(self):
        for rec in self:
            partner = rec.partner_id.name or 'sin partner'
            trig = dict(self._fields['trigger'].selection).get(rec.trigger, rec.trigger)
            date_str = rec.create_date.strftime('%Y-%m-%d %H:%M') if rec.create_date else ''
            rec.display_name = f"[{trig}] {partner} — {date_str}"

    # Precios por 1M tokens (USD). cache_write = TTL 1h (2x input), que es el que
    # usa el módulo. cache_read = 0.1x input. v1.11.0 — antes se cobraba TODO con
    # precios de Sonnet aunque el tráfico corre en Haiku 4.5, inflando el costo
    # reportado ~3x. Ahora el precio depende del modelo realmente usado.
    MODEL_PRICES = {
        'haiku': {'in': 1.0, 'out': 5.0, 'cw': 2.0, 'cr': 0.10},
        'sonnet': {'in': 3.0, 'out': 15.0, 'cw': 6.0, 'cr': 0.30},
        'opus': {'in': 15.0, 'out': 75.0, 'cw': 30.0, 'cr': 1.50},
        # v1.36.1 — generación 5 (precios de lista oct-2026). cw = 1h = 2x input.
        'sonnet5': {'in': 2.0, 'out': 10.0, 'cw': 4.0, 'cr': 0.20},
        'opus55': {'in': 4.0, 'out': 20.0, 'cw': 8.0, 'cr': 0.20},
        # v1.42 — Haiku 5.5 (hasta 100K tokens de prompt; más arriba, 5x).
        'haiku5': {'in': 0.10, 'out': 0.50, 'cw': 0.20, 'cr': 0.01},
    }

    @classmethod
    def _call_cost(cls, model_name, usage):
        """Costo USD de UNA llamada a la API según su `usage` (separa la caché de
        5 min, 1,25x, de la de 1 h, 2x)."""
        p = cls._prices_for_model(model_name)
        cc = usage.get('cache_creation') or {}
        cw_total = usage.get('cache_creation_input_tokens', 0) or 0
        cw_5m = cc.get('ephemeral_5m_input_tokens', 0) or 0
        cw_1h = max(cw_total - cw_5m, 0)
        inp = usage.get('input_tokens', 0) or 0
        cr = usage.get('cache_read_input_tokens', 0) or 0
        mult = 1.0
        if (model_name or '').startswith('claude-haiku-5') and inp + cw_total + cr > 100_000:
            mult = 5.0
        return mult * (inp * p['in'] + (usage.get('output_tokens', 0) or 0) * p['out']
                       + cw_5m * p['in'] * 1.25 + cw_1h * p['cw'] + cr * p['cr']) / 1_000_000

    @classmethod
    def _prices_for_model(cls, model_name):
        m = (model_name or '').lower()
        if m.startswith('claude-haiku-5'):
            return cls.MODEL_PRICES['haiku5']
        if m.startswith('claude-sonnet-5'):
            return cls.MODEL_PRICES['sonnet5']
        if m.startswith('claude-opus-5-5'):
            return cls.MODEL_PRICES['opus55']
        if 'sonnet' in m:
            return cls.MODEL_PRICES['sonnet']
        if 'opus' in m:
            return cls.MODEL_PRICES['opus']
        # default: Haiku (el modelo base del tráfico)
        return cls.MODEL_PRICES['haiku']

    @api.depends('input_tokens', 'output_tokens', 'cache_creation_input_tokens',
                 'cache_read_input_tokens', 'model_used', 'api_cost_usd',
                 'cache_creation_5m_tokens')
    def _compute_cost(self):
        for rec in self:
            if rec.api_cost_usd:
                rec.cost_usd = round(rec.api_cost_usd, 6)
                continue
            p = rec._prices_for_model(rec.model_used)
            cw_5m = rec.cache_creation_5m_tokens or 0
            cw_1h = max((rec.cache_creation_input_tokens or 0) - cw_5m, 0)
            cost = (
                (rec.input_tokens / 1_000_000) * p['in']
                + (rec.output_tokens / 1_000_000) * p['out']
                + (cw_5m / 1_000_000) * p['in'] * 1.25
                + (cw_1h / 1_000_000) * p['cw']
                + (rec.cache_read_input_tokens / 1_000_000) * p['cr']
            )
            rec.cost_usd = round(cost, 6)

    @api.model
    def today_spend_usd(self):
        """Gasto del día en hora Argentina (suma de cost_usd de las corridas)."""
        import pytz
        from ..services.helpers import now_ar
        start_local = now_ar(self.env).replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
        rows = self.sudo().read_group([('create_date', '>=', start_utc)],
                                      ['cost_usd:sum'], [])
        return (rows[0].get('cost_usd') or 0.0) if rows else 0.0

    # ─────────── Helpers para registrar tool calls ───────────
    def append_tool_call(self, tool_name, tool_input, tool_output, duration_ms=0, is_error=False):
        """Agrega una entrada al log de tool calls."""
        self.ensure_one()
        try:
            current = json.loads(self.tool_calls_log or '[]')
        except (json.JSONDecodeError, TypeError):
            current = []
        current.append({
            'tool_name': tool_name,
            'input': tool_input,
            'output': tool_output if not is_error else f"[ERROR] {tool_output}",
            'duration_ms': duration_ms,
            'is_error': is_error,
        })
        self.write({
            'tool_calls_log': json.dumps(current, ensure_ascii=False, default=str),
            'total_tool_calls': len(current),
        })

    def set_full_messages(self, messages_list):
        """Guarda el log completo de la conversación con Claude."""
        self.ensure_one()
        try:
            self.full_messages_log = json.dumps(messages_list, ensure_ascii=False, default=str)
        except Exception as e:
            _logger.warning("No se pudo serializar full_messages: %s", e)
            self.full_messages_log = "[error de serialización]"

    def mark_done(self, final_response=None):
        self.ensure_one()
        self.write({
            'state': 'done',
            'final_response': final_response or self.final_response or '',
        })

    def mark_error(self, error_msg):
        self.ensure_one()
        self.write({
            'state': 'error',
            'error_message': str(error_msg)[:5000],
        })
        _logger.error("AgentRun %s falló: %s", self.id, error_msg)

    # ─────────── Acciones de UI ───────────
    def action_view_tool_calls(self):
        """Abre un popup con el log de tool calls formateado."""
        self.ensure_one()
        try:
            data = json.loads(self.tool_calls_log or '[]')
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            formatted = self.tool_calls_log or ''
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'info',
                'title': _("Tool calls de la ejecución %s") % self.id,
                'message': formatted[:500] + ('...' if len(formatted) > 500 else ''),
                'sticky': True,
            },
        }

    # ─────────── Métodos de crons (entry points llamados desde XML) ───────────
    # Estos métodos los invocan los <ir.cron> definidos en data/cron_jobs.xml.
    # La lógica vive acá (Python) en lugar del XML porque el sandbox de
    # Odoo no permite imports ni asignaciones de atributos en código de cron.

    @api.model
    def _outside_contact_hours(self, cron_name):
        """v1.33 — True (y lo loguea) si está FUERA del horario en que Claudio puede
        iniciar mensajes (config.work_hours_start..end, hora Argentina, todos los
        días). Los crons frecuentes simplemente esperan a la próxima corrida.
        Bug real: seguimientos enviados a las 00:57, 05:24 y 23:25."""
        from ..services.helpers import within_contact_hours
        if within_contact_hours(self.env):
            return False
        _logger.info("%s: SKIP (fuera del horario de contacto; se retoma en horario)",
                     cron_name)
        return True

    @api.model
    def cron_cadence_phase2(self):
        """
        Cadencia Fase 2 — post-muestra.
        Se dispara periódicamente. Para cada lead en fase 2 con muestra enviada,
        si los días transcurridos están en [1, 3, 5, 6, 15] dispara el agente
        para que mande el siguiente mensaje de la cadencia.
        """
        from ..services.feature_flags import is_cron_enabled
        if not is_cron_enabled(self.env, 'enable_phase2_cadences'):
            _logger.info("cron_cadence_phase2: SKIP (flag enable_phase2_cadences=False)")
            return
        if self._outside_contact_hours('cron_cadence_phase2'):
            return
        from datetime import datetime
        from ..services.claude_client import dispatch_agent_for_cron

        now = fields.Datetime.now()
        Lead = self.env['crm.lead']
        Memory = self.env['cristal.agent.memory']

        leads = Lead.search([
            ('agent_managed', '=', True),
            ('agent_strategy_phase', '=', 'phase_2'),
            ('agent_sample_sent_at', '!=', False),
        ])
        CADENCE_DAYS = [1, 3, 5, 6, 15]

        for lead in leads:
            if not lead.partner_id:
                continue
            days_since = (now - lead.agent_sample_sent_at).days
            if days_since not in CADENCE_DAYS:
                continue
            memory = Memory.get_or_create(lead.partner_id)
            if memory.last_cadence_step_executed == days_since:
                continue
            if memory.is_takeover_active():
                continue
            try:
                dispatch_agent_for_cron(
                    self.env, 'cron_cadence', lead.partner_id, 'cadence_step_phase2',
                    extra_context={'days_since_sample': days_since, 'lead_id': lead.id},
                )
                memory.last_cadence_step_executed = days_since
            except Exception as e:
                _logger.exception("cron_cadence_phase2 falló para lead %s: %s", lead.id, e)

    @api.model
    def cron_cadence_phase3(self):
        """Cadencia Fase 3 — onboarding post 1ra compra."""
        from ..services.feature_flags import is_cron_enabled
        if not is_cron_enabled(self.env, 'enable_phase3_cadences'):
            _logger.info("cron_cadence_phase3: SKIP (flag enable_phase3_cadences=False)")
            return
        if self._outside_contact_hours('cron_cadence_phase3'):
            return
        from ..services.claude_client import dispatch_agent_for_cron

        now = fields.Datetime.now()
        Lead = self.env['crm.lead']
        Memory = self.env['cristal.agent.memory']

        leads = Lead.search([
            ('agent_managed', '=', True),
            ('agent_strategy_phase', '=', 'phase_3'),
            ('agent_first_purchase_at', '!=', False),
        ])
        CADENCE_DAYS_P3 = [3, 7, 15, 25]

        for lead in leads:
            if not lead.partner_id:
                continue
            days_since = (now - lead.agent_first_purchase_at).days
            if days_since not in CADENCE_DAYS_P3:
                continue
            memory = Memory.get_or_create(lead.partner_id)
            if memory.last_cadence_step_executed == days_since:
                continue
            if memory.is_takeover_active():
                continue
            try:
                dispatch_agent_for_cron(
                    self.env, 'cron_cadence', lead.partner_id, 'cadence_step_phase3',
                    extra_context={'days_since_first_purchase': days_since, 'lead_id': lead.id},
                )
                memory.last_cadence_step_executed = days_since
            except Exception as e:
                _logger.exception("cron_cadence_phase3 falló para lead %s: %s", lead.id, e)

    @api.model
    def cron_cadence_quoted(self):
        """
        Cadencia de SEGUIMIENTO DE COTIZACIÓN (Fase 2 — Cotización enviada).

        Para cada oportunidad en 'phase_2_quoted' (cotización enviada y sin
        cerrar), si los días desde que se envió la cotización están en [1, 3, 7]
        dispara al bot para que mande un seguimiento autónomo (recordatorio +
        20% off + formas de pago). La referencia de tiempo es la última
        sale.order vinculada a la oportunidad. Máx 3 toques (1/3/7) y para.
        """
        from ..services.feature_flags import is_cron_enabled
        if not is_cron_enabled(self.env, 'enable_quoted_cadences'):
            _logger.info("cron_cadence_quoted: SKIP (flag enable_quoted_cadences=False)")
            return
        if self._outside_contact_hours('cron_cadence_quoted'):
            return
        from ..services.claude_client import dispatch_agent_for_cron

        now = fields.Datetime.now()
        Lead = self.env['crm.lead']
        Memory = self.env['cristal.agent.memory']
        SaleOrder = self.env['sale.order']

        leads = Lead.search([
            ('agent_managed', '=', True),
            ('agent_strategy_phase', '=', 'phase_2_quoted'),
        ])
        CADENCE_DAYS_QUOTED = [1, 3]   # seguimientos suaves
        CANCEL_DAY = 7                 # +7 días sin confirmar → cancelar + reenganche

        # El partner operador (WhatsApp de Joaco) NO es un cliente: nunca le
        # mandamos cadencias aunque tenga una opp/cotización histórica.
        cfg = self.env['cristal.agent.config'].sudo().get_active()
        op_pid = cfg.owner_whatsapp_partner_id.id if cfg.owner_whatsapp_partner_id else None

        for lead in leads:
            if not lead.partner_id:
                continue
            if op_pid and lead.partner_id.id == op_pid:
                continue
            try:
                # Referencia: la última cotización (sale.order) colgada de la opp.
                order = SaleOrder.search(
                    [('opportunity_id', '=', lead.id)],
                    order='date_order desc', limit=1)
                ref = order.date_order if order else False
                if not ref:
                    continue

                # ── REVISÁ ANTES DE CONSULTAR (principio de operario real) ──
                # Si la ÚLTIMA cotización de la opp YA está CONFIRMADA (Joaco la cerró
                # a mano o por el bot), el negocio está hecho: NO se persigue al
                # cliente. Cortamos la cadencia y avanzamos la fase. Bug real (Silvia):
                # compró, la confirmaste vos, y al otro día el bot le escribía
                # "¿vas a querer los productos?" pensando que la venta no se gestionó.
                if order.state in ('sale', 'done'):
                    memory = Memory.get_or_create(lead.partner_id)
                    memory.last_cadence_step_executed = 999
                    try:
                        lead.write({'agent_strategy_phase': 'phase_3_first_purchase_done'})
                    except Exception:
                        pass
                    _logger.info(
                        "✅ cron_cadence_quoted: la cotización de %s ya está CONFIRMADA "
                        "— corto la cadencia y avanzo la fase (no persigo a quien ya "
                        "compró).", lead.partner_id.name)
                    continue

                days_since = (now - ref).days
                if days_since < 1:
                    continue
                memory = Memory.get_or_create(lead.partner_id)
                if memory.is_takeover_active():
                    continue
                last = memory.last_cadence_step_executed

                # +7 días sin confirmar: cancelar la(s) cotización(es) draft y
                # mandar un último mensaje de reenganche. Marca 999 = ya cancelado.
                if days_since >= CANCEL_DAY:
                    if last == 999:
                        continue
                    orders = SaleOrder.search([
                        ('opportunity_id', '=', lead.id), ('state', '=', 'draft')])
                    try:
                        if orders:
                            orders.action_cancel()
                    except Exception as e:
                        _logger.warning("No se pudo cancelar cotización lead %s: %s", lead.id, e)
                    dispatch_agent_for_cron(
                        self.env, 'cron_cadence', lead.partner_id, 'cadence_step_quote_cancel',
                        extra_context={'days_since_quote': days_since, 'lead_id': lead.id,
                                       'cotizacion': order.name, 'total': order.amount_total})
                    memory.last_cadence_step_executed = 999
                    continue

                # Catch-up del backlog (nunca seguido, last < 0) o seguimiento 1/3.
                is_catchup = (last is None or last < 0)
                if days_since not in CADENCE_DAYS_QUOTED and not is_catchup:
                    continue
                if last == days_since:
                    continue
                dispatch_agent_for_cron(
                    self.env, 'cron_cadence', lead.partner_id, 'cadence_step_quoted',
                    extra_context={
                        'days_since_quote': days_since,
                        'lead_id': lead.id,
                        'cotizacion': order.name,
                        'total': order.amount_total,
                    },
                )
                memory.last_cadence_step_executed = days_since
            except Exception as e:
                _logger.exception("cron_cadence_quoted falló para lead %s: %s", lead.id, e)

    @api.model
    def cron_levels_monthly(self):
        """Recálculo mensual de niveles BRONCE/PLATA/ORO de todos los Mayoristas."""
        from ..services.feature_flags import is_cron_enabled
        if not is_cron_enabled(self.env, 'enable_level_recalculation'):
            _logger.info("cron_levels_monthly: SKIP (flag enable_level_recalculation=False)")
            return
        from datetime import date, timedelta

        Partner = self.env['res.partner']
        mayorista_tag = self.env['res.partner.category'].search(
            [('name', '=', 'Mayorista')], limit=1
        )
        if not mayorista_tag:
            _logger.warning("cron_levels_monthly: no existe la etiqueta 'Mayorista'")
            return

        partners = Partner.search([('category_id', 'in', [mayorista_tag.id])])
        thresholds = [(500000, 'oro'), (200000, 'plata'), (50000, 'bronce'), (0, 'none')]
        rank = {'none': 0, 'bronce': 1, 'plata': 2, 'oro': 3}

        for partner in partners:
            try:
                avg = partner.compute_monthly_volume(months=3)
                new_level = 'none'
                for threshold, level in thresholds:
                    if avg >= threshold:
                        new_level = level
                        break
                old = partner.agent_level or 'none'
                if new_level == old:
                    continue
                grace = False
                if rank[new_level] < rank[old]:
                    grace = date.today() + timedelta(days=30)
                partner.write({
                    'agent_level': new_level,
                    'agent_level_computed_at': fields.Datetime.now(),
                    'agent_grace_period_until': grace,
                })
                partner.append_agent_observation(
                    "[CRON mensual] Nivel %s -> %s (volumen mensual prom $%s)"
                    % (old.upper(), new_level.upper(), int(avg))
                )
            except Exception as e:
                _logger.exception("cron_levels_monthly falló para partner %s: %s", partner.id, e)

    @api.model
    def cron_churn_detection(self):
        """Calcula churn_score diario para clientes Mayoristas activos."""
        from ..services.feature_flags import is_cron_enabled
        if not is_cron_enabled(self.env, 'enable_churn_detection'):
            _logger.info("cron_churn_detection: SKIP (flag enable_churn_detection=False)")
            return
        import json as _json

        now = fields.Datetime.now()
        Partner = self.env['res.partner']
        mayorista_tag = self.env['res.partner.category'].search(
            [('name', '=', 'Mayorista')], limit=1
        )
        if not mayorista_tag:
            return

        partners = Partner.search([
            ('category_id', 'in', [mayorista_tag.id]),
            ('agent_strategy_phase', 'in', ['phase_4_active_customer', 'phase_5_loyalty']),
        ])

        for partner in partners:
            try:
                score = 0
                signals = []

                if partner.agent_last_inbound_at:
                    days_quiet = (now - partner.agent_last_inbound_at).days
                    if days_quiet > 21:
                        score += 30
                        signals.append('silent_%sd' % days_quiet)

                if partner.agent_days_since_last_purchase and partner.agent_days_since_last_purchase > 30:
                    score += 30
                    signals.append('no_purchase_%sd' % partner.agent_days_since_last_purchase)

                if score > 0:
                    partner.write({
                        'agent_churn_score': score,
                        'agent_churn_signals': _json.dumps(signals),
                    })
                if score >= 50 and partner.agent_strategy_phase != 'churning':
                    partner.write({'agent_strategy_phase': 'churning'})
            except Exception as e:
                _logger.exception("cron_churn_detection falló para partner %s: %s", partner.id, e)

    @api.model
    def cron_pending_activities(self):
        """
        Cron PROACTIVO de actividades pendientes.

        Cada 2 horas revisa las mail.activity asignadas a Claudio (bot_user_id)
        cuyo deadline es <= hoy. Por cada una dispara al agente en modo
        "cumplir actividad": el agente lee el partner + lead + actividad,
        decide qué hacer, ejecuta, marca la actividad como done y agenda
        la siguiente.

        Este es el cron clave que convierte a Claudio en proactivo en vez
        de solo reactivo.
        """
        from ..services.claude_client import dispatch_agent_for_activity
        from ..services.feature_flags import is_cron_enabled

        # Chequear feature flag global del cron proactivo
        if not is_cron_enabled(self.env, 'enable_proactive_activities'):
            _logger.info(
                "cron_pending_activities: SKIP (enable_proactive_activities=False)"
            )
            return
        if self._outside_contact_hours('cron_pending_activities'):
            return

        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config or not config.enabled:
            _logger.info("cron_pending_activities: agente deshabilitado, salgo")
            return

        bot_user = config.bot_user_id
        if not bot_user:
            _logger.warning("cron_pending_activities: no hay bot_user_id configurado")
            return

        today = fields.Date.today()

        Activity = self.env['mail.activity'].sudo()
        pending_activities = Activity.search([
            ('user_id', '=', bot_user.id),
            ('date_deadline', '<=', today),
            ('res_model', 'in', ['crm.lead', 'res.partner']),
        ], order='date_deadline asc', limit=50)

        if not pending_activities:
            _logger.info("cron_pending_activities: no hay actividades pendientes para Claudio")
            return

        _logger.info(
            "🤖 cron_pending_activities: %s actividades pendientes para procesar",
            len(pending_activities)
        )

        Memory = self.env['cristal.agent.memory']

        # Anti-duplicación: trackea qué partners ya procesamos en esta corrida
        # para que NO disparemos múltiples runs del bot por el mismo cliente
        # cuando tiene varias actividades vencidas.
        processed_partners = set()
        skipped_dup = 0

        for activity in pending_activities:
            try:
                # Resolver partner
                partner = None
                lead = None
                if activity.res_model == 'crm.lead':
                    lead = self.env['crm.lead'].sudo().browse(activity.res_id)
                    if lead.exists():
                        partner = lead.partner_id
                elif activity.res_model == 'res.partner':
                    partner = self.env['res.partner'].sudo().browse(activity.res_id)
                    if partner.exists():
                        lead = self.env['crm.lead'].sudo().search([
                            ('partner_id', '=', partner.id),
                            ('agent_managed', '=', True),
                            ('active', '=', True),
                        ], limit=1, order='create_date desc')

                if not partner or not partner.exists():
                    _logger.warning(
                        "Actividad %s sin partner válido, la marco como done",
                        activity.id
                    )
                    activity.action_done()
                    continue

                # Anti-duplicación intra-corrida
                if partner.id in processed_partners:
                    _logger.info(
                        "Actividad %s saltada (partner %s ya procesado en esta corrida)",
                        activity.id, partner.name
                    )
                    skipped_dup += 1
                    continue

                # Anti-duplicación inter-corrida: si tuvo run cron_cadence en los
                # últimos 30 min, no volvemos a disparar (evita loops y ahorra tokens)
                from datetime import datetime, timedelta
                recent_run = self.env['cristal.agent.run'].sudo().search([
                    ('partner_id', '=', partner.id),
                    ('trigger', '=', 'cron_cadence'),
                    ('create_date', '>=', datetime.now() - timedelta(minutes=30)),
                ], limit=1)
                if recent_run:
                    _logger.info(
                        "Actividad %s saltada: ya hay run cron_cadence reciente "
                        "para %s (id=%s, %s)",
                        activity.id, partner.name, recent_run.id, recent_run.create_date
                    )
                    skipped_dup += 1
                    continue

                # ─── ANTI-LOOP por canal WA inexistente ───
                # Si esta actividad ya tuvo 2+ runs cron_cadence en últimos 7 días
                # significa que el bot está intentando contactar al cliente pero
                # algo falla (típicamente no hay canal WA o no hay template).
                # Cerramos la actividad y delegamos a Joaco para revisión manual.
                stuck_runs = self.env['cristal.agent.run'].sudo().search_count([
                    ('partner_id', '=', partner.id),
                    ('trigger', '=', 'cron_cadence'),
                    ('create_date', '>=', datetime.now() - timedelta(days=7)),
                ])
                if stuck_runs >= 2:
                    # v1.31 — Claudio es ULTRAAUTÓNOMO: NO le carga actividades a
                    # Joaco. Antes, un cliente "trabado" (sin canal WA / sin
                    # template) generaba una actividad manual para Joaco. Ahora la
                    # actividad se cierra sin más y queda el log; si de verdad hace
                    # falta que Joaco intervenga, el bot ya escala por el canal
                    # interno desde el propio run.
                    _logger.warning(
                        "Actividad %s STUCK para %s (%s runs en 7d). Cierro la "
                        "actividad sin generar tarea para Joaco (ultraautónomo).",
                        activity.id, partner.name, stuck_runs
                    )
                    try:
                        activity.action_done()
                    except Exception as e:
                        _logger.exception("Error cerrando actividad trabada: %s", e)
                    continue

                # Saltar si el partner tiene takeover humano activo
                memory = Memory.get_or_create(partner)
                if memory.is_takeover_active():
                    _logger.info(
                        "Actividad %s saltada: partner %s en takeover humano",
                        activity.id, partner.name
                    )
                    continue

                # Disparar al agente en modo "cumplir actividad"
                dispatch_agent_for_activity(
                    self.env, partner, lead, activity,
                )
                processed_partners.add(partner.id)
                # NO marcamos done acá — el agente lo hace después de ejecutar

            except Exception as e:
                _logger.exception(
                    "cron_pending_activities falló para actividad %s: %s",
                    activity.id, e
                )

    @api.model
    def cron_retry_failed_whatsapp(self):
        """
        Cron que cada 5 minutos busca mensajes whatsapp.message en estado error
        de las últimas 2 horas y los reintenta automáticamente.

        Esto soluciona el caso típico de "Error de red" puntual de WhatsApp
        Business API que normalmente Joaco tenía que reintentar a mano.

        Máximo 3 reintentos por mensaje (campo `failure_reason` se actualiza).
        Solo reintenta mensajes de cuenta WA del bot (los que el agente generó).
        """
        from datetime import datetime, timedelta
        from ..services.feature_flags import is_cron_enabled

        # Si send_whatsapp está apagado, no tiene sentido reintentar
        if not is_cron_enabled(self.env, 'enable_send_whatsapp'):
            _logger.info(
                "cron_retry_failed_whatsapp: SKIP (enable_send_whatsapp=False)"
            )
            return

        threshold = datetime.now() - timedelta(hours=2)
        WhatsApp = self.env['whatsapp.message'].sudo()

        # Buscar mensajes fallidos recientes
        failed_messages = WhatsApp.search([
            ('state', 'in', ['error', 'failed']),
            ('create_date', '>=', threshold),
            ('message_type', '=', 'outbound'),
        ], limit=20, order='create_date asc')

        if not failed_messages:
            return

        _logger.info(
            "🔄 cron_retry_failed_whatsapp: %s mensajes fallidos para reintentar",
            len(failed_messages)
        )

        retried = 0
        for msg in failed_messages:
            try:
                # Contar reintentos previos (guardamos en un campo char si existe)
                # Si llegó a 3 reintentos, marcamos como definitivo y escalamos
                retry_count = 0
                if hasattr(msg, 'failure_reason') and msg.failure_reason:
                    if 'retry_attempt' in (msg.failure_reason or ''):
                        try:
                            retry_count = int(msg.failure_reason.split('retry_attempt=')[1].split(';')[0])
                        except Exception:
                            retry_count = 0

                if retry_count >= 3:
                    _logger.warning(
                        "Mensaje WA %s alcanzó 3 reintentos, NO reintento más",
                        msg.id
                    )
                    continue

                # Reintentar — usar el método nativo
                if hasattr(msg, '_send_message'):
                    msg._send_message()
                    retried += 1
                    _logger.info(
                        "🔄 Reintento %s/3 mensaje WA id=%s → estado: %s",
                        retry_count + 1, msg.id, msg.state
                    )
            except Exception as e:
                _logger.warning(
                    "Error reintentando WA id=%s: %s",
                    msg.id, e
                )

        _logger.info(
            "🔄 cron_retry_failed_whatsapp: reintentados %s/%s",
            retried, len(failed_messages)
        )

    @api.model
    def cron_weekly_offer_broadcast(self):
        """
        Cron de broadcast semanal de oferta — corre los LUNES a las 14hs.

        Manda la oferta vigente marcada "Va en el envío de los lunes" a los Mayoristas
        (ver _weekly_broadcast_partners). Usa el template de
        agent_config.weekly_offer_template_id: {{1}} = nombre cliente (automático),
        {{2}} = offer.broadcast_text.

        Si no hay oferta marcada, avisa en el canal interno y no manda nada.
        """
        from datetime import datetime, date
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config or not config.enabled:
            return

        if not getattr(config, 'enable_weekly_offer_broadcast', False) \
                or not config.enable_send_whatsapp_templates:
            _logger.info("cron_weekly_offer_broadcast: SKIP (broadcast o templates deshabilitados)")
            return

        template = config.weekly_offer_template_id
        if not template or template.status != 'approved':
            _logger.warning(
                "cron_weekly_offer_broadcast: NO se ejecuta — "
                "weekly_offer_template_id sin configurar o no aprobado"
            )
            return

        # Safety: verificar que sea lunes (en caso de re-cron manual o reschedule)
        weekday = datetime.now().weekday()  # 0=lun, 6=dom
        if weekday != 0:
            _logger.info(
                "cron_weekly_offer_broadcast: SKIP — hoy es %s, no lunes",
                ['lun','mar','mié','jue','vie','sáb','dom'][weekday]
            )
            return

        # v1.40: SOLO la oferta marcada "Va en el envío de los lunes", con su texto para
        # el cliente. Antes tomaba la de mayor prioridad (el 19/10 hubiera sido la promo
        # de cierre de Sur-Oeste a 604 mayoristas) y mandaba la descripción interna.
        offer = self.env['cristal.agent.offer'].get_weekly_broadcast_offer()
        if not offer:
            _logger.warning("cron_weekly_offer_broadcast: SKIP — no hay oferta marcada "
                            "para el envío de los lunes")
            self._post_internal(
                "📣 Hoy no salió la oferta semanal de los lunes: no hay ninguna oferta "
                "vigente marcada 'Va en el envío de los lunes' (Claudio → Ofertas).")
            return

        partners = self._weekly_broadcast_partners(offer)
        if not partners:
            _logger.info("cron_weekly_offer_broadcast: no hay mayoristas elegibles")
            return

        _logger.info(
            "📣 cron_weekly_offer_broadcast: %s mayoristas elegibles. "
            "Oferta: '%s'. Template: '%s'",
            len(partners), offer.name, template.name
        )

        from ..services.tools.send_whatsapp_template import SendWhatsappTemplate
        sender = SendWhatsappTemplate()
        env = self.env(context=dict(self.env.context, from_cristal_agent=True))
        text = ' '.join((offer.broadcast_text or '').split())
        sent = errors = 0
        for partner in partners:
            try:
                # {{1}} = nombre (automático); {{2}} = el texto de la oferta.
                result = sender._execute(
                    env=env, partner_id=partner.id, template_name=template.name,
                    variables=[text],
                    wa_account_id=template.wa_account_id.id if template.wa_account_id else None)
                if result and result.get('ok'):
                    sent += 1
                    # Cada envío queda confirmado: si el cron se corta, lo enviado no se pierde.
                    self.env.cr.commit()
                else:
                    errors += 1
                    _logger.warning("Broadcast falló para %s: %s", partner.name,
                                    (result or {}).get('error', '-'))
            except Exception as e:
                errors += 1
                _logger.exception("Error broadcast para %s: %s", partner.name, e)

        offer.increment_communicated()
        self._post_internal(
            f"📣 Oferta semanal enviada: «{offer.name}». Salió a {sent} mayoristas"
            + (f" ({errors} con error)" if errors else "") + ".")
        _logger.info("📣 cron_weekly_offer_broadcast COMPLETADO: enviados=%s, errors=%s, "
                     "elegibles=%s", sent, errors, len(partners))

    @api.model
    def _weekly_broadcast_partners(self, offer):
        """Mayoristas que reciben el envío de los lunes: con teléfono, sin 'Fuera de
        zona', fuera de los circuitos excluidos por la oferta, sin takeover humano, sin
        una plantilla recibida en las últimas 24 h y sin números repetidos."""
        from datetime import datetime, timedelta
        import re
        Category = self.env['res.partner.category'].sudo()
        mayorista = Category.search([('name', '=', 'Mayorista')], limit=1)
        if not mayorista:
            return self.env['res.partner']
        fuera_zona = Category.search([('name', '=', 'Fuera de zona')], limit=1)
        config = self.env['cristal.agent.config'].sudo().get_active()
        domain = [('category_id', 'in', [mayorista.id]), ('active', '=', True),
                  ('agent_opt_out', '=', False),
                  '|', ('mobile', '!=', False), ('phone', '!=', False)]
        if fuera_zona:
            domain.append(('category_id', 'not in', [fuera_zona.id]))
        if config and config.owner_whatsapp_partner_id:
            domain.append(('id', '!=', config.owner_whatsapp_partner_id.id))
        if offer.excluded_circuit_ids:
            domain += ['|', ('truck_circuit_id', '=', False),
                       ('truck_circuit_id', 'not in', offer.excluded_circuit_ids.ids)]
        partners = self.env['res.partner'].sudo().search(domain)

        Memory = self.env['cristal.agent.memory'].sudo()
        takeover = set(Memory.search([('partner_id', 'in', partners.ids),
                                      ('human_takeover', '=', True)]).mapped('partner_id').ids)
        recent = self.env['whatsapp.message'].sudo().search([
            ('message_type', '=', 'outbound'), ('wa_template_id', '!=', False),
            ('create_date', '>=', datetime.now() - timedelta(hours=24))])
        recent_digits = {re.sub(r'\D', '', m.mobile_number or '')[-8:] for m in recent}
        seen = set()
        result = self.env['res.partner']
        for p in partners:
            digits = re.sub(r'\D', '', p.mobile or p.phone or '')[-8:]
            if len(digits) < 8 or digits in seen or digits in recent_digits \
                    or p.id in takeover:
                continue
            mem = Memory.search([('partner_id', '=', p.id)], limit=1)
            if mem and mem.is_takeover_active():
                continue
            seen.add(digits)
            result |= p
        return result

    @api.model
    def _post_internal(self, body):
        config = self.env['cristal.agent.config'].sudo().get_active()
        channel = config.internal_channel_id if config else False
        if channel:
            channel.sudo().with_context(from_cristal_agent=True).message_post(
                body=body, message_type='comment', subtype_xmlid='mail.mt_comment')
