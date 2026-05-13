# -*- coding: utf-8 -*-
"""
Extensión de crm.lead.

Cada lead de mayorista tiene asociada una fase de la estrategia (agent_strategy_phase).
Cuando el agente actualiza la fase, el módulo mueve automáticamente el stage_id
del CRM al correspondiente (mapping definido en cristal.agent.config).
"""
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

PHASE_TO_STAGE_FIELD = {
    'phase_1': 'crm_stage_phase_1_id',
    'phase_2': 'crm_stage_phase_2_sample_id',
    'phase_2_quoted': 'crm_stage_phase_2_quoted_id',
    'phase_3': 'crm_stage_phase_3_won_id',
    'phase_4': 'crm_stage_phase_3_won_id',
    'phase_5': 'crm_stage_phase_3_won_id',
}


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    agent_managed = fields.Boolean(
        string="Gestionado por agente",
        default=False,
        help="True si este lead lo creó/gestiona el agente Claudio.",
    )

    agent_strategy_phase = fields.Selection([
        ('phase_1', 'Fase 1 — Calificación'),
        ('phase_2', 'Fase 2 — Muestra entregada'),
        ('phase_2_quoted', 'Fase 2 — Propuesta enviada'),
        ('phase_3', 'Fase 3 — Onboarding (cliente nuevo)'),
        ('phase_4', 'Fase 4 — Cliente activo'),
        ('phase_5', 'Fase 5 — Fidelización'),
        ('won', 'Ganado'),
        ('lost', 'Perdido'),
    ], string="Fase comercial",
        help="Fase actual del cliente en la estrategia mayorista.",
    )

    agent_qualification_data = fields.Text(
        string="Datos de calificación",
        help="JSON con las respuestas a las 5 preguntas iniciales.",
    )

    agent_sample_sent_at = fields.Datetime(string="Muestra enviada el")
    agent_sample_expected_delivery = fields.Date(
        string="Entrega prevista de muestra",
        help="Día hábil siguiente al envío (vie-dom → lunes).",
    )
    agent_sample_received_at = fields.Datetime(string="Muestra recibida el")
    agent_first_purchase_at = fields.Datetime(string="Primera compra realizada")
    agent_first_purchase_amount = fields.Float(string="Monto 1ra compra")

    agent_kit_sent = fields.Boolean(string="Kit Bienvenida enviado", default=False)
    agent_kit_sent_at = fields.Datetime(string="Kit enviado el")

    # ─────────── Sync automático fase → stage CRM ───────────

    def _sync_agent_phase_to_stage(self):
        """Para cada lead, si tiene agent_strategy_phase y hay mapping
        configurado, mueve stage_id al stage CRM correspondiente."""
        Config = self.env['cristal.agent.config'].sudo()
        config = Config.get_active()
        for lead in self:
            if not lead.agent_strategy_phase:
                continue
            stage_field = PHASE_TO_STAGE_FIELD.get(lead.agent_strategy_phase)
            if not stage_field:
                continue
            target_stage = getattr(config, stage_field, False)
            if target_stage and lead.stage_id.id != target_stage.id:
                _logger.info(
                    "Sync lead %s: %s → stage CRM '%s'",
                    lead.id, lead.agent_strategy_phase, target_stage.name
                )
                lead.with_context(no_sync_agent_phase=True).write({
                    'stage_id': target_stage.id,
                })

    def write(self, vals):
        result = super().write(vals)
        if 'agent_strategy_phase' in vals and not self.env.context.get('no_sync_agent_phase'):
            self._sync_agent_phase_to_stage()
        return result

    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        leads_to_sync = leads.filtered(lambda l: l.agent_strategy_phase)
        if leads_to_sync:
            leads_to_sync._sync_agent_phase_to_stage()
        return leads
