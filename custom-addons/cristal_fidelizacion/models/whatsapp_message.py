# -*- coding: utf-8 -*-
"""Respuestas a los mensajes de fidelización.

Cuando el cliente toca un botón de una plantilla nuestra, lo registramos en el
contacto y actuamos: pedido en borrador, tarea al responsable o baja de promociones.
No respondemos texto libre: la conversación la sigue Claudio o una persona.
"""
import logging
import re
import unicodedata
from datetime import timedelta

from odoo import _, api, fields, models

from odoo.addons.cristal_minorista.models.res_partner import wa_key

_logger = logging.getLogger(__name__)

REPLY_WINDOW_HOURS = 72


def _norm(text):
    text = unicodedata.normalize('NFKD', re.sub(r'<[^>]+>', '', text or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', text).strip().lower()


class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records.filtered(lambda m: m.message_type == 'inbound' or m.state == 'received'):
            try:
                with self.env.cr.savepoint():
                    record._cristal_fid_handle_reply()
            except Exception:  # noqa: BLE001 — nunca romper la recepción del mensaje
                _logger.exception("fidelización: error procesando respuesta wa.msg %s", record.id)
        return records

    def _cristal_fid_handle_reply(self):
        key = wa_key(self.mobile_number)
        body = _norm(self.body)
        if not key or not body:
            return
        since = fields.Datetime.now() - timedelta(hours=REPLY_WINDOW_HOURS)
        touch = self.env['cristal.fid.touch'].sudo().search([
            ('state', '=', 'sent'), ('date', '>=', since), ('reply', '=', False),
            ('partner_id.cristal_wa_key', '=', key)], limit=1)
        if not touch:
            return
        buttons = touch.flow_id.buttons()
        normalized = [_norm(b) for b in buttons]
        if body not in normalized:
            touch.write({'reply': 'other', 'reply_text': (self.body or '')[:250],
                         'reply_date': fields.Datetime.now()})
            return
        index = normalized.index(body)
        is_optout = index == len(buttons) - 1 and len(buttons) > 1 and 'no me' in body
        if is_optout:
            reply = 'optout'
        elif index == 0:
            reply = 'positive'
        else:
            reply = 'negative'
        touch.write({'reply': reply, 'reply_text': buttons[index], 'reply_date': fields.Datetime.now()})
        touch._cristal_fid_act()


class CristalFidTouch(models.Model):
    _inherit = 'cristal.fid.touch'

    def _cristal_fid_act(self):
        """Acción según la respuesta del cliente."""
        self.ensure_one()
        partner = self.partner_id
        if self.reply == 'optout':
            partner.sudo().write({'cristal_mkt_optout': True})
            return
        if self.flow_code == 'satisfaccion':
            if self.reply == 'negative':
                self._cristal_fid_activity(_("Cliente respondió «%s» a la encuesta: llamarlo y resolver.",
                                             self.reply_text))
            return
        if self.reply != 'positive':
            return
        order = self._cristal_fid_draft_order()
        self._cristal_fid_activity(
            _("%(name)s respondió «%(reply)s» a %(flow)s. Confirmar pedido y día de entrega.",
              name=partner.name, reply=self.reply_text, flow=self.flow_id.name),
            record=order or partner)

    def _cristal_fid_last_product(self):
        """Último producto de la familia que compró el cliente."""
        if not self.family_id:
            return False
        patterns = self.family_id._patterns()
        partners = self.env['res.partner'].sudo().search(
            [('commercial_partner_id', '=', self.partner_id.commercial_partner_id.id)])
        for model in ('pos.order.line', 'sale.order.line'):
            for line in self.env[model].sudo().search([('order_id.partner_id', 'in', partners.ids)],
                                                      order='id desc', limit=200):
                name = (line.product_id.name or '').lower()
                if any(p in name for p in patterns):
                    return line.product_id
        return False

    def _cristal_fid_draft_order(self):
        """Cotización en borrador para que el vendedor la confirme."""
        product = self._cristal_fid_last_product()
        origin = 'recordatorio' if self.flow_code == 'reposicion' else 'reactivacion'
        vals = {'partner_id': self.partner_id.id,
                'note': _("Generado por %s. El cliente respondió «%s».", self.flow_id.name, self.reply_text)}
        if product:
            vals['order_line'] = [(0, 0, {'product_id': product.id, 'product_uom_qty': 1})]
        if self.flow_id.responsible_user_id:
            vals['user_id'] = self.flow_id.responsible_user_id.id
        order = self.env['sale.order'].sudo().with_context(
            cristal_origin=origin, cristal_origin_ref='fid-%s' % self.id).create(vals)
        self.sale_order_id = order
        return order

    def _cristal_fid_activity(self, note, record=None):
        record = record or self.partner_id
        user = self.flow_id.responsible_user_id or self.env.ref('base.user_admin')
        record.sudo().activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                        summary=_("Fidelización: %s", self.flow_id.name), note=note)
