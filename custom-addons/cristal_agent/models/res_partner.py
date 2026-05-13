# -*- coding: utf-8 -*-
"""
Extensión de res.partner con los campos que el agente necesita
para llevar registro del cliente como un empleado lo haría.
"""
import logging
from datetime import datetime, timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ─────────── Lo que sabe el bot del cliente (texto libre acumulativo) ───────────
    agent_observations = fields.Text(
        string="Observaciones del agente",
        help="El agente escribe acá lo que va aprendiendo del cliente: "
             "preferencias, patrones de compra, episodios destacados, etc. "
             "Se actualiza automáticamente.",
    )

    # ─────────── Sistema de niveles (Fase 4 de la estrategia mayorista) ───────────
    agent_level = fields.Selection([
        ('none', 'Sin nivel asignado'),
        ('bronce', 'BRONCE'),
        ('plata', 'PLATA'),
        ('oro', 'ORO'),
    ], string="Nivel mayorista", default='none', tracking=True)

    agent_level_computed_at = fields.Datetime(
        string="Nivel calculado el",
        help="Última vez que el cron mensual recalculó el nivel.",
    )

    agent_monthly_volume_avg = fields.Float(
        string="Volumen mensual promedio (últimos 3 meses)",
        digits='Product Price',
        help="Calculado automáticamente cada mes basándose en account.move (facturas).",
    )

    agent_grace_period_until = fields.Date(
        string="Mes de gracia hasta",
        help="Si bajó de nivel, mantiene beneficios hasta esta fecha. Default: 1 mes desde la bajada.",
    )

    # ─────────── Estrategia comercial (en qué fase está este cliente) ───────────
    agent_strategy_phase = fields.Selection([
        ('not_qualified', 'No calificado'),
        ('disqualified_to_crilimp', 'Derivado a CRILIMP'),
        ('phase_1_qualifying', 'Fase 1 — Calificando'),
        ('phase_1_qualified', 'Fase 1 — Calificado, esperando muestra'),
        ('phase_2_post_sample', 'Fase 2 — Post-muestra (días 0-15)'),
        ('phase_3_first_purchase_done', 'Fase 3 — 1ra compra hecha'),
        ('phase_3_onboarding', 'Fase 3 — Onboarding (días 0-25)'),
        ('phase_4_active_customer', 'Fase 4 — Cliente activo (con nivel)'),
        ('phase_5_loyalty', 'Fase 5 — En programa de fidelización'),
        ('churning', 'En riesgo de churn'),
        ('lost', 'Perdido (>45 días sin compra)'),
        ('reactivated', 'Recuperado'),
    ], string="Fase comercial actual", default='not_qualified', tracking=True)

    agent_phase_started_at = fields.Datetime(
        string="Fase iniciada el",
    )

    # ─────────── Última actividad detectada por el agente ───────────
    agent_last_inbound_at = fields.Datetime(
        string="Último mensaje recibido",
    )
    agent_last_outbound_at = fields.Datetime(
        string="Último mensaje enviado",
    )
    agent_last_purchase_at = fields.Datetime(
        string="Última compra",
        compute='_compute_last_purchase',
    )
    agent_days_since_last_purchase = fields.Integer(
        string="Días desde última compra",
        compute='_compute_days_since_last_purchase',
    )

    # ─────────── Detección de churn ───────────
    agent_churn_score = fields.Float(
        string="Churn score (0-100)",
        default=0.0,
        help="Cuánto más alto, más probable que el cliente deje de comprar. "
             "Calculado por cron diario.",
    )
    agent_churn_signals = fields.Text(
        string="Señales de churn detectadas",
        help="JSON con las señales que el bot detectó.",
    )

    # ─────────── Programa de referidos ───────────
    agent_referred_by_id = fields.Many2one(
        'res.partner',
        string="Cliente que lo refirió",
    )
    agent_referrals_count = fields.Integer(
        string="Referidos hechos",
        compute='_compute_referrals_count',
    )

    # ─────────── Computeds ───────────
    @api.depends_context('uid')
    def _compute_last_purchase(self):
        SaleOrder = self.env['sale.order'].sudo()
        for partner in self:
            sale = SaleOrder.search([
                ('partner_id', '=', partner.id),
                ('state', 'in', ['sale', 'done']),
            ], order='date_order desc', limit=1)
            partner.agent_last_purchase_at = sale.date_order if sale else False

    @api.depends('agent_last_purchase_at')
    def _compute_days_since_last_purchase(self):
        now = fields.Datetime.now()
        for partner in self:
            if partner.agent_last_purchase_at:
                delta = now - partner.agent_last_purchase_at
                partner.agent_days_since_last_purchase = delta.days
            else:
                partner.agent_days_since_last_purchase = -1

    @api.depends_context('uid')
    def _compute_referrals_count(self):
        for partner in self:
            partner.agent_referrals_count = self.search_count([
                ('agent_referred_by_id', '=', partner.id)
            ])

    # ─────────── Helpers ───────────
    def is_mayorista(self):
        """Devuelve True si tiene la etiqueta Mayorista (id 16)."""
        self.ensure_one()
        return any(t.name == 'Mayorista' for t in self.category_id)

    def is_consumidor_final(self):
        """Devuelve True si tiene la etiqueta Consumidor Final (id 2)."""
        self.ensure_one()
        return any(t.name == 'Consumidor Final' for t in self.category_id)

    def is_empresa(self):
        """Devuelve True si tiene la etiqueta EMPRESA (id 1)."""
        self.ensure_one()
        return any(t.name == 'EMPRESA' for t in self.category_id)

    def append_agent_observation(self, text):
        """Agrega una observación al campo de observaciones."""
        self.ensure_one()
        timestamp = fields.Datetime.now().strftime('%Y-%m-%d %H:%M')
        existing = self.agent_observations or ""
        new_entry = f"[{timestamp}] {text}"
        # Mantenemos solo las últimas ~50 observaciones para no explotar
        lines = (existing.split('\n') if existing else [])[-49:] + [new_entry]
        self.agent_observations = '\n'.join(lines)
        _logger.info("📝 Observación agregada para %s: %s", self.name, text[:80])

    def compute_monthly_volume(self, months=3):
        """
        Calcula el volumen mensual promedio del partner basado en facturas
        de venta confirmadas en los últimos N meses.
        """
        self.ensure_one()
        date_from = fields.Datetime.now() - timedelta(days=30 * months)
        invoices = self.env['account.move'].sudo().search([
            ('partner_id', '=', self.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', date_from.date()),
        ])
        total = sum(inv.amount_untaxed_signed for inv in invoices)
        avg = total / months if months else 0
        self.agent_monthly_volume_avg = avg
        return avg
