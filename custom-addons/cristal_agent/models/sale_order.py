# -*- coding: utf-8 -*-
"""
Hook en sale.order.

Cuando una cotización se CONFIRMA (pasa a 'sale'/'done') — la cierre Joaco a mano
o el bot — avanzamos la fase comercial del cliente y cortamos la cadencia de
seguimiento. Objetivo: el bot NUNCA persigue a quien ya compró ni lo trata como
cliente nuevo. El estado del cliente queda siempre correcto (principio de
"operario que revisa antes de consultar").

Bugs reales que esto corrige:
- Silvia: compró, Joaco confirmó a mano, y al otro día el bot le escribía
  "¿vas a querer los productos?" pensando que la venta nunca se gestionó.
- Ariel: 3ra compra y el bot lo trataba como primera (fase nunca avanzaba).
"""
import logging
from odoo import models, api

_logger = logging.getLogger(__name__)

# Fases desde las que tiene sentido avanzar a "primera compra hecha".
_ADVANCEABLE_PHASES = (
    'not_qualified', 'phase_1_qualifying', 'phase_1_qualified',
    'phase_2_post_sample', 'phase_2_quoted',
)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') in ('sale', 'done'):
            for order in self:
                try:
                    order._cristal_on_confirm()
                except Exception as e:
                    _logger.warning("cristal_on_confirm falló para %s: %s", order.id, e)
        return res

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            try:
                order._cristal_on_confirm()
            except Exception as e:
                _logger.warning("cristal_on_confirm (action_confirm) falló para %s: %s",
                                order.id, e)
        return res

    def _cristal_on_confirm(self):
        """Avanza la fase del lead agent-managed y corta la cadencia."""
        self.ensure_one()
        opp = self.opportunity_id
        if opp and getattr(opp, 'agent_managed', False) \
                and opp.agent_strategy_phase in _ADVANCEABLE_PHASES:
            try:
                opp.write({'agent_strategy_phase': 'phase_3_first_purchase_done'})
                _logger.info(
                    "✅ Venta confirmada: %s → fase 'primera compra hecha'.",
                    opp.partner_id.name if opp.partner_id else opp.name)
            except Exception as e:
                _logger.warning("No pude avanzar la fase del lead %s: %s", opp.id, e)
        # Cortar la cadencia de seguimiento del cliente (no perseguir a quien compró).
        if self.partner_id:
            mem = self.env['cristal.agent.memory'].sudo().search(
                [('partner_id', '=', self.partner_id.id)], limit=1)
            if mem:
                mem.last_cadence_step_executed = 999
