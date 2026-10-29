# -*- coding: utf-8 -*-
"""Circuito del pedido de consumidor final, igual en los tres canales (local, web, WhatsApp).

1. Se confirma solo: Claudio (confirm_cf_order), la web pagada con Mercado Pago, y también la
   web con "Pago en Local" / transferencia (antes quedaba como presupuesto y nadie la confirmaba).
2. Al confirmarse: una actividad "Preparar y entregar" (o "Preparar para retiro") para quien
   reparte, con fecha, productos, pago y dirección; y un aviso en el canal interno.
3. Al entregarse (remito validado): la actividad se cierra sola y queda la fecha de entrega.
4. Control: cada mañana, los pedidos con entrega atrasada se avisan en el canal interno.
"""
import logging
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

DELIVERY_USER_PARAM = 'cristal_minorista.delivery_user_id'
DEFAULT_DELIVERY_USER = 15          # Guillermo
ACTIVITY_PREFIX = 'Pedido CF'
NO_DELIVERY_WEEKDAYS = (2, 6)       # miércoles (sale el camión de la ruta) y domingo


def _next_delivery_day(day):
    day = day + timedelta(days=1)
    while day.weekday() in NO_DELIVERY_WEEKDAYS:
        day += timedelta(days=1)
    return day


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    cristal_is_cf = fields.Boolean(string='Consumidor final', compute='_compute_cristal_is_cf',
                                   store=True, index=True)
    cristal_delivered_date = fields.Date(string='Entregado el', copy=False)
    cristal_payment_note = fields.Char(string='Pago (consumidor final)', copy=False,
                                       help='Efectivo contra entrega, transferencia, Mercado Pago…')

    @api.depends('pricelist_id', 'partner_id.cristal_customer_type')
    def _compute_cristal_is_cf(self):
        for order in self:
            name = (order.pricelist_id.name or '').strip().upper()
            order.cristal_is_cf = name.startswith('L.C') or (
                not name and order.partner_id.cristal_customer_type == 'cf')

    def action_confirm(self):
        res = super().action_confirm()
        for order in self.filtered('cristal_is_cf'):
            try:
                with self.env.cr.savepoint():
                    order._cristal_cf_after_confirm()
            except Exception:  # noqa: BLE001 — el circuito nunca frena la confirmación
                _logger.exception("pedido CF: no pude armar la entrega de %s", order.name)
        return res

    # ── Confirmación ──────────────────────────────────────────────
    @api.model
    def _cristal_delivery_user(self):
        uid = int(self.env['ir.config_parameter'].sudo().get_param(DELIVERY_USER_PARAM, DEFAULT_DELIVERY_USER))
        return self.env['res.users'].sudo().browse(uid).exists() or self.env.ref('base.user_admin')

    def _cristal_cf_after_confirm(self):
        self.ensure_one()
        if 'cristal_delivery_mode' in self._fields and not self.cristal_delivery_mode:
            self.cristal_delivery_mode = 'retiro' if self.carrier_id.delivery_type == 'in_store' else 'envio'
        if not self.cristal_payment_note:
            tx = self.transaction_ids.sorted('id')[-1:] if self.transaction_ids else False
            if tx:
                self.cristal_payment_note = tx.provider_id.name
            elif self.cristal_origin == 'whatsapp_ia':
                self.cristal_payment_note = _('Efectivo o transferencia (acordado por WhatsApp)')
        pickup = self.cristal_delivery_mode == 'retiro'
        today = fields.Date.context_today(self)
        deadline = today if pickup else _next_delivery_day(today)
        ship = self.partner_shipping_id or self.partner_id
        lines = '\n'.join(f"• {int(l.product_uom_qty) if l.product_uom_qty == int(l.product_uom_qty) else l.product_uom_qty} × {l.product_id.display_name}"
                          for l in self.order_line if not l.display_type and not l.is_delivery)
        where = _("Retira en el local (San Martín 2350)") if pickup else \
            f"{ship.street or _('SIN DIRECCIÓN')}, {ship.city or ''}".strip(', ')
        note = (f"<p><b>{_('Cliente')}:</b> {self.partner_id.name} · {self.partner_id.mobile or self.partner_id.phone or ''}<br/>"
                f"<b>{_('Entrega')}:</b> {where}<br/>"
                f"<b>{_('Pago')}:</b> {self.cristal_payment_note or '—'}<br/>"
                f"<b>{_('Total')}:</b> ${self.amount_total:,.0f}<br/>"
                f"<b>{_('Origen')}:</b> {dict(self._fields['cristal_origin'].selection).get(self.cristal_origin, '')}</p>"
                f"<pre>{lines}</pre>").replace(',', '.')
        summary = f"{ACTIVITY_PREFIX} · {'Preparar para retiro' if pickup else 'Preparar y entregar'} · {self.name}"
        if not self.activity_ids.filtered(lambda a: a.summary == summary):
            self.activity_schedule('mail.mail_activity_data_todo', user_id=self._cristal_delivery_user().id,
                                   date_deadline=deadline, summary=summary, note=note)
        if self.cristal_origin != 'whatsapp_ia':   # Claudio ya avisa los suyos
            self._cristal_post_internal(
                f"🛒 Pedido de consumidor final confirmado por {dict(self._fields['cristal_origin'].selection).get(self.cristal_origin, 'otro canal')}: "
                f"<b>{self.name}</b> de {self.partner_id.name}, ${self.amount_total:,.0f}. "
                f"{'Retira en el local' if pickup else 'Envío a ' + where}. Pago: {self.cristal_payment_note or '—'}.".replace(',', '.'))

    def _cristal_post_internal(self, body):
        config = self.env['cristal.agent.config'].sudo().get_active() if 'cristal.agent.config' in self.env else False
        channel = config.internal_channel_id if config else False
        if channel:
            channel.sudo().with_context(from_cristal_agent=True).message_post(
                body=body, message_type='comment', subtype_xmlid='mail.mt_comment')

    # ── Entrega ───────────────────────────────────────────────────
    def _cristal_cf_delivered(self):
        for order in self:
            order.cristal_delivered_date = fields.Date.context_today(order)
            for act in order.activity_ids.filtered(lambda a: (a.summary or '').startswith(ACTIVITY_PREFIX)):
                act.action_feedback(feedback=_('Entregado'))
            order.message_post(body=_("Pedido de consumidor final entregado."))

    # ── Control diario ────────────────────────────────────────────
    @api.model
    def _cron_cf_followup(self):
        """Pedidos de consumidor final confirmados y no entregados con la actividad vencida."""
        today = fields.Date.context_today(self)
        late = self.env['mail.activity'].sudo().search([
            ('res_model', '=', 'sale.order'), ('summary', 'like', ACTIVITY_PREFIX + '%'),
            ('date_deadline', '<', today)])
        if not late:
            return
        rows = []
        for act in late:
            order = self.browse(act.res_id).exists()
            if order and order.state == 'sale' and not order.cristal_delivered_date:
                rows.append(f"• {order.name} — {order.partner_id.name} — ${order.amount_total:,.0f} — "
                            f"vencía el {act.date_deadline.strftime('%d/%m')} ({act.user_id.name})".replace(',', '.'))
        if rows:
            self._cristal_post_internal("⚠️ <b>Pedidos de consumidor final sin entregar (atrasados)</b><br/>" + '<br/>'.join(rows))


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        res = super()._action_done()
        try:
            orders = self.filtered(lambda p: p.picking_type_code == 'outgoing' and p.sale_id.cristal_is_cf).sale_id
            done = orders.filtered(lambda o: not o.cristal_delivered_date and all(
                p.state in ('done', 'cancel') for p in o.picking_ids.filtered(lambda p: p.picking_type_code == 'outgoing')))
            done.sudo()._cristal_cf_delivered()
        except Exception:  # noqa: BLE001
            _logger.exception("pedido CF: no pude cerrar la entrega")
        return res


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _post_process(self):
        res = super()._post_process()
        # "Pago en Local" / transferencia (proveedor custom) deja la venta como presupuesto:
        # al consumidor final se le confirma igual que por WhatsApp (paga al recibir o retirar).
        for tx in self.filtered(lambda t: t.state == 'pending' and t.provider_id.code == 'custom'):
            orders = tx.sale_order_ids.filtered(lambda o: o.cristal_is_cf and o.state in ('draft', 'sent'))
            for order in orders:
                try:
                    with self.env.cr.savepoint():
                        order.cristal_payment_note = tx.provider_id.name
                        order.with_context(send_email=True).action_confirm()
                except Exception:  # noqa: BLE001
                    _logger.exception("pedido CF web: no pude confirmar %s", order.name)
        return res
