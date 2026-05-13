# -*- coding: utf-8 -*-
"""
Memoria conversacional del agente por cliente.

Se reusa la lógica del módulo `chatbot_whatsapp` viejo (takeover humano,
flow_state, comandos /on /off) y se extiende con campos específicos de la
estrategia mayorista: fase actual, datos de calificación, última cadencia
ejecutada, etc.

Hay UNA memoria por partner (constraint único).
"""
import logging
from datetime import datetime, timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Estados del flujo de calificación de mayorista (Fase 1)
QUALIFICATION_FLOWS = [
    ('q_nombre_email', 'Esperando nombre + email'),
    ('q_tipo_comercio', 'Esperando si tiene comercio o arranca'),
    ('q_productos', 'Esperando productos que vende'),
    ('q_volumen', 'Esperando volumen mensual'),
    ('q_zona', 'Esperando zona del comercio'),
    ('q_completed', 'Calificación completada'),
]


class CristalAgentMemory(models.Model):
    _name = 'cristal.agent.memory'
    _description = "Cristal Agent — Memoria por cliente"
    _order = 'last_interaction_at desc'

    partner_id = fields.Many2one(
        'res.partner',
        string="Cliente",
        required=True,
        ondelete='cascade',
        index=True,
    )
    phone = fields.Char(string="Teléfono", index=True)

    # ─────────── Estado del flujo conversacional ───────────
    flow_state = fields.Selection(
        QUALIFICATION_FLOWS + [
            ('idle', 'Idle'),
            ('cf_handling', 'Atendiendo CF'),
            ('empresa_handling', 'Atendiendo Empresa'),
            ('post_sample', 'Post-muestra (Fase 2)'),
            ('onboarding', 'Onboarding (Fase 3)'),
            ('paused', 'Pausado por humano'),
        ],
        string="Estado del flujo",
        default='idle',
    )

    last_intent_detected = fields.Char(string="Última intención detectada")
    last_interaction_at = fields.Datetime(
        string="Última interacción",
        default=fields.Datetime.now,
    )

    # ─────────── Buffer de calificación (Fase 1) ───────────
    qual_name = fields.Char(string="Nombre (calificación)")
    qual_email = fields.Char(string="Email (calificación)")
    qual_has_business = fields.Selection([
        ('yes', 'Ya tiene comercio'),
        ('starting', 'Está por arrancar'),
    ], string="¿Tiene comercio?")
    qual_products = fields.Text(string="Productos que vende")
    qual_monthly_volume = fields.Char(
        string="Volumen mensual estimado",
        help="Texto libre como 'unos 100 litros' o '$80.000 al mes'",
    )
    qual_volume_amount = fields.Float(
        string="Volumen en pesos (estimado)",
        help="Si Claude pudo extraer un monto numérico",
    )
    qual_zone = fields.Char(string="Zona del local")
    qual_qualified = fields.Boolean(
        string="¿Calificó?",
        help="True si pasa el filtro $50k/mes + zona cubierta. False si se deriva a CRILIMP.",
    )

    # ─────────── Lead asociado ───────────
    lead_id = fields.Many2one(
        'crm.lead',
        string="Lead asociado",
        help="El crm.lead que se creó al calificar.",
    )

    # ─────────── Cadencias activas ───────────
    cadence_phase = fields.Selection([
        ('none', 'Ninguna'),
        ('phase_2_post_sample', 'Fase 2 — Post-muestra'),
        ('phase_3_onboarding', 'Fase 3 — Onboarding 1ra compra'),
        ('phase_4_levels', 'Fase 4 — Niveles'),
        ('phase_5_loyalty', 'Fase 5 — Fidelización'),
        ('recovery_45d', 'Recuperación 45 días'),
    ], string="Cadencia activa", default='none')

    cadence_started_at = fields.Datetime(
        string="Inicio de cadencia",
        help="Cuándo arrancó la cadencia activa. Se usa para calcular qué paso tocaría hoy.",
    )
    last_cadence_step_executed = fields.Integer(
        string="Último paso de cadencia ejecutado",
        default=0,
    )

    # ─────────── Toma de control humana (reusa lógica del módulo viejo) ───────────
    human_takeover = fields.Boolean(
        string="Takeover humano activo",
        default=False,
        help="Si es True, el bot NO procesa mensajes de este cliente.",
    )
    takeover_until = fields.Datetime(
        string="Takeover hasta",
        help="Si está vacío y takeover está activo, es indefinido. "
             "Si tiene fecha, se reactiva el bot al pasar esa hora.",
    )
    takeover_reason = fields.Char(string="Motivo del takeover")

    # ─────────── Counters ───────────
    total_messages_received = fields.Integer(string="Mensajes recibidos", default=0)
    total_messages_sent = fields.Integer(string="Mensajes enviados", default=0)
    total_escalations = fields.Integer(string="Escalaciones a Joaco", default=0)

    # ─────────── Constraints ───────────
    _sql_constraints = [
        ('partner_id_unique', 'unique(partner_id)',
         'Solo puede haber una memoria por cliente.'),
    ]

    # ─────────── Métodos ───────────
    @api.model
    def get_or_create(self, partner):
        """Obtiene la memoria del partner, o la crea si no existe."""
        if not partner:
            return False
        memory = self.search([('partner_id', '=', partner.id)], limit=1)
        if not memory:
            memory = self.sudo().create({
                'partner_id': partner.id,
                'phone': partner.mobile or partner.phone or '',
            })
            _logger.info("🧠 Memoria creada para %s (id=%s)", partner.name, memory.id)
        return memory

    def write(self, vals):
        """Actualiza last_interaction_at automáticamente en cada escritura."""
        if 'last_interaction_at' not in vals:
            vals['last_interaction_at'] = fields.Datetime.now()
        return super().write(vals)

    def is_takeover_active(self):
        """Devuelve True si el bot debe ignorar mensajes de este cliente."""
        self.ensure_one()
        if not self.human_takeover:
            return False
        # Indefinido
        if not self.takeover_until:
            return True
        # Con vencimiento: chequeamos si ya venció
        now = fields.Datetime.now()
        if self.takeover_until > now:
            return True
        # Venció: reactivamos
        self.write({
            'human_takeover': False,
            'takeover_until': False,
            'takeover_reason': False,
        })
        _logger.info("🔁 Takeover expirado, reactivando bot para %s", self.partner_id.name)
        return False

    def activate_takeover(self, reason="Intervención manual", duration_hours=1):
        """Pausa el bot para este cliente."""
        self.ensure_one()
        until = fields.Datetime.now() + timedelta(hours=duration_hours) if duration_hours else False
        self.write({
            'human_takeover': True,
            'takeover_until': until,
            'takeover_reason': reason,
        })
        _logger.info("🤫 Takeover activado para %s — motivo: %s", self.partner_id.name, reason)

    def deactivate_takeover(self):
        """Reactiva el bot para este cliente."""
        self.ensure_one()
        self.write({
            'human_takeover': False,
            'takeover_until': False,
            'takeover_reason': False,
        })
        _logger.info("✅ Takeover desactivado para %s", self.partner_id.name)

    def increment_received(self):
        self.ensure_one()
        self.total_messages_received = (self.total_messages_received or 0) + 1

    def increment_sent(self):
        self.ensure_one()
        self.total_messages_sent = (self.total_messages_sent or 0) + 1

    def increment_escalation(self):
        self.ensure_one()
        self.total_escalations = (self.total_escalations or 0) + 1

    @api.model
    def cron_reactivate_expired_takeovers(self):
        """Cron: reactiva takeovers vencidos."""
        now = fields.Datetime.now()
        expired = self.search([
            ('human_takeover', '=', True),
            ('takeover_until', '!=', False),
            ('takeover_until', '<=', now),
        ])
        if expired:
            _logger.info("🔁 Cron: reactivando %s takeovers expirados", len(expired))
            expired.write({
                'human_takeover': False,
                'takeover_until': False,
                'takeover_reason': False,
            })
