# -*- coding: utf-8 -*-
"""
Cadencias proactivas del agente.

Representa cada paso del proceso comercial que el bot ejecuta automáticamente
(via cron de actividades). Joaco edita cada cadencia desde la vista:
- Cuándo se dispara (evento + offset de días)
- Qué template de WhatsApp usa
- Qué variables se llenan

El bot, al procesar una actividad proactiva, busca la cadencia correspondiente
y la usa para armar el mensaje.
"""
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class CristalAgentCadence(models.Model):
    _name = 'cristal.agent.cadence'
    _description = "Cristal Agent — Cadencia proactiva"
    _order = 'sequence, id'

    name = fields.Char(
        string="Nombre",
        required=True,
        help="Nombre descriptivo del paso. Ej: 'Chequeo post-muestra día +2'",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    # v1.9.0: filtro por tipo de cliente
    client_type = fields.Selection([
        ('mayorista', 'Mayorista'),
        ('institucional', 'Institucional'),
        ('both', 'Ambos'),
    ], string="Tipo de cliente",
       default='mayorista',
       required=True,
       help="Las cadencias institucionales por ahora se manejan vía "
            "base.automation del CRM, no acá. Default 'mayorista' para no "
            "tocar las 10 cadencias existentes.")

    phase = fields.Selection([
        ('phase_1', 'Fase 1 — Calificación'),
        ('phase_2', 'Fase 2 — Conversión (post-muestra)'),
        ('phase_2_quoted', 'Fase 2 — Cotización enviada'),
        ('phase_3', 'Fase 3 — Onboarding (1ra compra)'),
        ('phase_4', 'Fase 4 — Cliente activo'),
        ('phase_5', 'Fase 5 — Fidelización'),
        ('any', 'Cualquiera'),
    ], string="Fase del cliente", required=True, default='phase_2')

    trigger_event = fields.Selection([
        ('sample_sent', 'Muestra enviada'),
        ('sample_delivery', 'Entrega prevista de muestra'),
        ('first_purchase', '1ra compra realizada'),
        ('last_purchase', 'Última compra'),
        ('qualification_done', 'Calificación completada'),
        ('inactivity', 'Sin interacción'),
        ('promised_purchase', 'Fecha prometida de compra'),
        ('manual', 'Disparo manual'),
    ], string="Evento que dispara", required=True, default='sample_sent')

    trigger_days_offset = fields.Integer(
        string="Días offset",
        default=2,
        help="Cuántos días después del evento. Negativo = antes del evento "
             "(ej: -1 = un día antes de la fecha prometida de compra).",
    )

    # ─── Template de WhatsApp ───
    whatsapp_template_id = fields.Many2one(
        'whatsapp.template',
        string="Template WhatsApp",
        help="Template aprobado por Meta que se usa cuando la ventana 24hs "
             "del cliente está cerrada. Si no tiene template, el bot intenta "
             "mensaje libre — si la ventana está cerrada, escala a Joaco.",
    )
    template_variables_guide = fields.Text(
        string="Guía de variables",
        help="Explicale al bot qué tiene que poner en cada {{N}} del template. "
             "Ej: '{{1}}=nombre del cliente, {{2}}=descripción de la oferta vigente'.",
    )

    wa_account_id = fields.Many2one(
        'whatsapp.account',
        string="Cuenta WhatsApp (opcional)",
        help="Si está vacío, usa la cuenta default del agent_config.",
    )

    # ─── Comportamiento ───
    max_runs_per_partner = fields.Integer(
        string="Máx. veces por cliente",
        default=1,
        help="Cuántas veces esta cadencia se puede ejecutar para el mismo cliente. "
             "Default 1 — útil para evitar spam.",
    )

    requires_open_window = fields.Boolean(
        string="Requiere ventana abierta",
        default=False,
        help="Si está marcado, este paso solo se ejecuta si la ventana de 24hs "
             "del cliente está abierta. Si está cerrada, escala a Joaco.",
    )

    description = fields.Text(
        string="Descripción interna",
        help="Notas para Joaco sobre cuándo/cómo se usa este paso.",
    )

    instructions_for_bot = fields.Text(
        string="Instrucciones para el bot",
        help="Lo que el bot tiene que hacer cuando se dispara esta cadencia. "
             "Aparece en el contexto que recibe Claudio.",
    )

    @api.model
    def get_active_for_phase(self, phase):
        """Devuelve las cadencias activas para una fase (incluyendo 'any')."""
        return self.search([
            ('active', '=', True),
            ('phase', 'in', [phase, 'any']),
        ], order='sequence')
