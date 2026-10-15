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
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Fases desde las que tiene sentido avanzar a "primera compra hecha".
_ADVANCEABLE_PHASES = (
    'not_qualified', 'phase_1_qualifying', 'phase_1_qualified',
    'phase_2_post_sample', 'phase_2_quoted',
)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Ruta del camión (v1.32): salida (miércoles desde v1.35) a la que va esta orden.
    route_departure_id = fields.Many2one(
        'cristal.agent.route.departure', string="Salida de ruta (camión)",
        index=True, copy=False, ondelete='set null',
        help="Salida de la ruta del camión a la que se asignó esta orden.")
    # Bidones (v1.33): el cliente ya respondió cuántos vacíos tiene para el recambio.
    cristal_bidones_answered = fields.Boolean(
        string="Bidones consultados", copy=False,
        help="El cliente ya dijo cuántos bidones vacíos tiene para el recambio.")

    # Envío sin cargo acordado (v1.37): Joaco/el equipo le prometió el envío sin
    # cargo a este cliente. Con esto en True, NINGÚN cálculo agrega la línea de
    # flete de la ruta, aunque el pedido quede por debajo del umbral. Solo lo marca
    # un usuario interno (vendedores); Claudio no puede tocarlo.
    route_free_shipping_granted = fields.Boolean(
        string="Envío sin cargo acordado", copy=False, tracking=True,
        groups='sales_team.group_sale_salesman',
        help="Marcalo si se le prometió el envío sin cargo a este cliente: la "
             "cotización no lleva flete de ruta aunque no llegue al monto de envío "
             "sin cargo. Claudio nunca lo marca.")

    # ───────────────────── Flete de la ruta (v1.37) ─────────────────────
    def _cristal_freight_product(self, config):
        if config and config.route_freight_product_id:
            return config.route_freight_product_id
        return self.env['product.product'].sudo().search(
            [('default_code', '=', 'FLETE-ZONA')], limit=1)

    def _cristal_shipping_base(self, config):
        """Base del umbral de ENVÍO SIN CARGO: subtotal sin IVA de los PRODUCTOS, sin
        la línea de flete ni los bidones nuevos (misma base que el mínimo de la ruta).
        Joaco (15/10/2026): el bidón deja ~15% de margen; si contara, 2 bidones
        ($7.000) le ahorrarían al cliente $9.000 de flete."""
        self.ensure_one()
        excluded = self._cristal_freight_product(config)
        if config and config.bidon_product_id:
            excluded |= config.bidon_product_id
        return sum(self.order_line.filtered(
            lambda l: l.product_id not in excluded).mapped('price_subtotal'))

    def _cristal_apply_route_freight(self, config, free_from):
        """Saca el flete anterior y lo vuelve a poner SOLO si corresponde:
        sin 'envío sin cargo acordado' y con la base por debajo de free_from
        (config.route_free_shipping_from, o el umbral de rescate). Devuelve
        (flete, base)."""
        self.ensure_one()
        freight_product = self._cristal_freight_product(config)
        if freight_product:
            self.order_line.filtered(lambda l: l.product_id == freight_product).unlink()
        base = self._cristal_shipping_base(config)
        freight = 0.0
        if freight_product and not self.sudo().route_free_shipping_granted \
                and base < (free_from or 0.0):
            freight = config.route_freight_amount
            self.write({'order_line': [(0, 0, {
                'product_id': freight_product.id, 'product_uom_qty': 1,
                'price_unit': freight, 'discount': 0.0})]})
            # Última palabra sobre el precio: la Lista Mayorista tiene una regla
            # global de -20% que Odoo podría aplicar al flete.
            self.order_line.filtered(lambda l: l.product_id == freight_product).write(
                {'price_unit': freight, 'discount': 0.0})
        return freight, base

    def write(self, vals):
        # Claudio (contexto from_cristal_agent) nunca marca el envío sin cargo.
        if self.env.context.get('from_cristal_agent') \
                and 'route_free_shipping_granted' in vals:
            vals = dict(vals)
            vals.pop('route_free_shipping_granted')
        res = super().write(vals)
        # Si se acordó el envío sin cargo, se saca el flete de las cotizaciones.
        if vals.get('route_free_shipping_granted'):
            config = self.env['cristal.agent.config'].sudo().get_active()
            for order in self.filtered(lambda o: o.state in ('draft', 'sent')):
                freight = order._cristal_freight_product(config)
                if freight:
                    order.order_line.filtered(lambda l: l.product_id == freight).unlink()
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
