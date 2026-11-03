# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    cristal_supplier_msg_date = fields.Datetime(
        string="Último envío al proveedor", readonly=True, copy=False,
        help="Cuándo el agente de Compras le mandó al proveedor el pedido de precio o la orden.")
    cristal_order_sent = fields.Boolean(string="Orden enviada al proveedor", readonly=True, copy=False)

    def button_confirm(self):
        """Sergio (03/11): con la orden aprobada, el PDF sale al proveedor sin volver a
        preguntar. Si la confirma alguien que no es responsable de Compras, queda el botón
        «Enviar al proveedor» para que lo haga Sergio."""
        res = super().button_confirm()
        Compras = self.env['cristal.compras']
        manager = self.env.su or self.env.user.has_group('purchase.group_purchase_manager')
        for order in self.filtered(lambda o: o.state == 'purchase' and not o.cristal_order_sent):
            if manager:
                order._cristal_send_order()
            else:
                Compras._alert(order, _("Orden %s confirmada: falta el OK para mandarla al proveedor", order.name))
        return res

    def _cristal_send_order(self):
        Compras = self.env['cristal.compras']
        for order in self:
            ok, _detail = Compras.send(order, order.partner_id, 'order')
            if ok:
                order.write({'cristal_order_sent': True, 'cristal_supplier_msg_date': fields.Datetime.now()})

    def action_cristal_send_order(self):
        """Botón «Enviar al proveedor» (orden confirmada que no salió)."""
        for order in self:
            if order.state not in ('purchase', 'done'):
                raise UserError(_("La orden %s todavía no está confirmada.", order.name))
        self._cristal_send_order()
        return True

    def action_cristal_request_quote(self):
        """Botón «Pedir precio y fecha»: con el OK de Sergio (que es quien lo aprieta)."""
        Compras = self.env['cristal.compras']
        for order in self:
            if order.state not in ('draft', 'sent'):
                raise UserError(_("El pedido de precio se manda desde una solicitud de presupuesto."))
            ok, _detail = Compras.send(order, order.partner_id, 'quote')
            if ok:
                vals = {'cristal_supplier_msg_date': fields.Datetime.now()}
                if order.state == 'draft':
                    vals['state'] = 'sent'
                order.write(vals)
        return True

    def _message_post_after_hook(self, message, msg_vals):
        """Las respuestas del proveedor por mail a la orden: lista → se guarda; precio,
        fecha o condiciones → actividad para Compras."""
        res = super()._message_post_after_hook(message, msg_vals)
        if message.message_type == 'email' and message.author_id \
                and message.author_id.commercial_partner_id == self.partner_id.commercial_partner_id:
            self.env['cristal.compras'].sudo().process_supplier_message(
                message.author_id, message, 'mail', order=self)
        return res
