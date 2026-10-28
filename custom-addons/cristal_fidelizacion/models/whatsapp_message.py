# -*- coding: utf-8 -*-
"""Respuestas a los mensajes de fidelización.

Cuando el cliente toca un botón de una plantilla nuestra, lo registramos en el
contacto y actuamos: pedido en borrador, tarea al responsable o baja de promociones.
Si responde "Muy bien" a la encuesta, le pedimos la reseña de Google por el mismo chat;
el resto de la conversación la sigue Claudio o una persona.
"""
import logging
import re
import unicodedata
from datetime import timedelta

from odoo import _, fields, models

from odoo.addons.cristal_minorista.models.res_partner import wa_key

_logger = logging.getLogger(__name__)

REPLY_WINDOW_HOURS = 72
REVIEW_GAP_DAYS = 180
REVIEW_TEXT = ("Gracias, {name} 🙌 Si tenés 30 segundos, ¿nos dejás una reseña en Google? "
               "Nos ayuda mucho a que más gente de Río Cuarto nos conozca: {url}")


def _norm(text):
    text = unicodedata.normalize('NFKD', re.sub(r'<[^>]+>', '', text or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', text).strip().lower()


class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    def _maybe_trigger_agent(self, wa_message):
        """Antes de que conteste Claudio: si es la respuesta a un mensaje de fidelización,
        se registra y se actúa. Si ya le contestamos nosotros (pedido de reseña), Claudio
        no escribe encima."""
        if wa_message.message_type == 'inbound' or wa_message.state == 'received':
            try:
                with self.env.cr.savepoint():
                    if wa_message._cristal_fid_handle_reply() == 'answered':
                        return
            except Exception:  # noqa: BLE001 — nunca romper la recepción del mensaje
                _logger.exception("fidelización: error procesando respuesta wa.msg %s", wa_message.id)
        return super()._maybe_trigger_agent(wa_message)

    def _cristal_fid_handle_reply(self):
        """Devuelve 'answered' si ya le respondimos al cliente desde acá."""
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
        if touch.flow_code == 'satisfaccion' and reply == 'positive' and self._cristal_fid_send_review(touch):
            return 'answered'

    def _cristal_fid_send_review(self, touch):
        """Le pide la reseña de Google por el mismo chat (la ventana de 24 h está abierta
        porque el cliente acaba de responder). Una vez cada 180 días por cliente."""
        partner = touch.partner_id
        url = self.env['ir.config_parameter'].sudo().get_param('cristal_fidelizacion.google_review_url')
        last = partner.cristal_review_asked_date
        if not url or (last and last > fields.Datetime.now() - timedelta(days=REVIEW_GAP_DAYS)):
            return False
        mail = self.mail_message_id
        if not mail or mail.model != 'discuss.channel':
            return False
        from .engine import _first_name
        text = REVIEW_TEXT.format(name=_first_name(partner), url=url)
        bot_partner = self.env.ref('base.partner_root')
        reply_mail = self.env['mail.message'].sudo().with_context(from_cristal_agent=True).create({
            'author_id': bot_partner.id,
            'body': text,
            'message_type': 'whatsapp_message',
            'model': 'discuss.channel',
            'res_id': mail.res_id,
            'subtype_id': self.env.ref('mail.mt_comment').id,
        })
        wa = self.sudo().create({
            'mail_message_id': reply_mail.id,
            'wa_account_id': self.wa_account_id.id,
            'mobile_number': self.mobile_number,
            'message_type': 'outbound',
            'state': 'outgoing',
        })
        wa._send_message()
        partner.sudo().cristal_review_asked_date = fields.Datetime.now()
        touch.review_requested = True
        return True


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
        config = self.env['cristal.agent.config'].sudo().get_active()
        if config and config.enabled:
            # Claudio ve el mensaje y la respuesta en el contexto del cliente: cotiza y
            # cierra él (si armáramos otra cotización acá, quedarían dos).
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
