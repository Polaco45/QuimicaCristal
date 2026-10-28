# -*- coding: utf-8 -*-
"""Lealtad Cristal para el consumidor final.

- Los tickets de caja a nombre del Consumidor Final Anónimo suman puntos al cliente que
  dejó su WhatsApp (pos.order.cristal_customer_id).
- Puntos de bienvenida la primera vez que se anota.
- El saldo y el próximo premio se muestran en la caja al anotarlo.
"""
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

LOYALTY_PROGRAM = 'Lealtad Cristal'
WELCOME_POINTS = 300


def _loyalty_program(env):
    return env['loyalty.program'].sudo().search(
        [('name', '=', LOYALTY_PROGRAM), ('program_type', '=', 'loyalty')], limit=1)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    cristal_fid_welcome_given = fields.Boolean(string='Recibió puntos de bienvenida', copy=False)
    cristal_review_asked_date = fields.Datetime(string='Último pedido de reseña en Google', copy=False)

    def _cristal_loyalty_card(self, create=False):
        self.ensure_one()
        program = _loyalty_program(self.env)
        Card = self.env['loyalty.card'].sudo()
        if not program:
            return Card
        card = Card.search([('program_id', '=', program.id), ('partner_id', '=', self.id)], limit=1)
        if not card and create:
            card = Card.create({'program_id': program.id, 'partner_id': self.id, 'points': 0})
        return card

    def _cristal_add_points(self, points, description, order=None):
        self.ensure_one()
        card = self._cristal_loyalty_card(create=True)
        if not card or not points:
            return
        card.points += points
        if 'loyalty.history' in self.env:
            vals = {'card_id': card.id, 'description': description, 'issued': points, 'used': 0}
            if order:
                vals.update(order_model=order._name, order_id=order.id)
            self.env['loyalty.history'].sudo().create(vals)

    def cristal_loyalty_status(self):
        """Saldo y próximo premio: {'points', 'next_reward', 'missing'}."""
        self.ensure_one()
        program = _loyalty_program(self.env)
        points = self._cristal_loyalty_card().points if program else 0.0
        rewards = program.reward_ids.filtered('active').sorted('required_points') if program else []
        nxt = next((r for r in rewards if r.required_points > points), None)
        return {
            'points': int(points),
            'next_reward': nxt.description if nxt else False,
            'missing': int(nxt.required_points - points) if nxt else 0,
        }

    @api.model
    def cristal_pos_identify(self, phone, name=None, partner_id=None):
        res = super().cristal_pos_identify(phone, name=name, partner_id=partner_id)
        if res.get('id'):
            partner = self.sudo().browse(res['id'])
            try:
                if not partner.cristal_fid_welcome_given and _loyalty_program(self.env):
                    partner._cristal_add_points(WELCOME_POINTS, _("Bienvenida (alta por WhatsApp en la caja)"))
                    partner.cristal_fid_welcome_given = True
                res.update(partner.cristal_loyalty_status())
            except Exception:  # noqa: BLE001 — el alta vale aunque fallen los puntos
                _logger.exception("lealtad: no pude sumar la bienvenida a %s", partner.id)
        return res


class CristalFidEngine(models.AbstractModel):
    _inherit = 'cristal.fid.engine'

    @api.model
    def _cron_run(self, flows=None):
        res = super()._cron_run(flows=flows)
        self._cristal_reset_anonymous_points()
        return res

    @api.model
    def _cristal_reset_anonymous_points(self):
        """El Consumidor Final Anónimo no junta puntos: si no, la caja le termina aplicando
        premios solos (Joaco ya los puso en 0 una vez; el punto de venta los vuelve a sumar)."""
        anon = self.env['cristal.minorista.engine']._anonymous_partner_id()
        program = _loyalty_program(self.env)
        if not (anon and program):
            return
        cards = self.env['loyalty.card'].sudo().search([
            ('program_id', '=', program.id), ('partner_id', '=', anon), ('points', '!=', 0)])
        if cards:
            _logger.info("lealtad: Anónimo de nuevo en 0 (tenía %s puntos)", sum(cards.mapped('points')))
            cards.write({'points': 0})


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()
        program = _loyalty_program(self.env)
        rule = program.rule_ids.filtered(lambda r: r.reward_point_mode == 'money')[:1] if program else False
        if not rule:
            return res
        for order in self.filtered(lambda o: o.cristal_customer_id and o.cristal_customer_id != o.partner_id):
            if order.amount_total < (rule.minimum_amount or 0):
                continue
            try:
                with self.env.cr.savepoint():
                    order.cristal_customer_id._cristal_add_points(
                        order.amount_total * rule.reward_point_amount, order.name, order)
            except Exception:  # noqa: BLE001 — nunca frenar el cobro
                _logger.exception("lealtad: no pude sumar puntos del ticket %s", order.id)
        return res
