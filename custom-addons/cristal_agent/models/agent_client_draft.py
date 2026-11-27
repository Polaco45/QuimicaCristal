# -*- coding: utf-8 -*-
"""v1.83 — Borradores de respuesta a clientes del WhatsApp de empresas (modo borrador).

Cada registro es una consulta: lo que escribió el cliente, el borrador, la cotización que
se armó (si era un pedido) y qué decidió Joaco. Ver services/client_consult.py.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .agent_supplier_draft import STATES, _SelftestRollback
from ..services import client_consult as cc
from ..services import purchase_consult as pc

_logger = logging.getLogger(__name__)

OPEN_STATES = ('collecting', 'pending', 'correcting')


class CristalAgentClientDraft(models.Model):
    _name = 'cristal.agent.client.draft'
    _description = "Cristal Agent — borrador de respuesta a cliente de empresas"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char("Código", compute='_compute_name', store=True)
    state = fields.Selection(STATES, "Estado", default='collecting', required=True,
                             index=True, tracking=True)
    kind = fields.Selection(cc.KINDS, "Tipo", index=True)
    channel_id = fields.Many2one('discuss.channel', "Chat", ondelete='set null', index=True)
    wa_account_id = fields.Many2one('whatsapp.account', "Cuenta de WhatsApp")
    partner_id = fields.Many2one('res.partner', "Contacto", ondelete='set null')
    client_id = fields.Many2one('res.partner', "Cliente", ondelete='set null',
                                compute='_compute_client', store=True)
    client_name = fields.Char("Quién escribió", compute='_compute_client', store=True)
    mobile_number = fields.Char("Celular")
    incoming_text = fields.Text("Qué escribió")
    last_inbound_at = fields.Datetime("Último mensaje")
    draft_text = fields.Text("Borrador")
    note = fields.Char("Nota para Joaco")
    unmatched_text = fields.Text("Renglones sin identificar")
    order_id = fields.Many2one('sale.order', "Cotización armada", ondelete='set null')
    order_amount = fields.Monetary("Total de la cotización", related='order_id.amount_total',
                                   currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='order_id.currency_id')
    correction_text = fields.Text("Corrección pedida")
    asked_at = fields.Datetime("Listo para aprobar")
    notify_via = fields.Selection([('whatsapp', 'WhatsApp'), ('screen', 'Solo en pantalla')],
                                  "Aviso por")
    audio_attachment_ids = fields.Many2many(
        'ir.attachment', 'cristal_client_draft_audio_rel', 'draft_id', 'attachment_id',
        string="Notas de voz por transcribir")
    notify_mail_message_id = fields.Many2one('mail.message', "Mensaje de consulta",
                                             ondelete='set null', index=True)
    resolved_at = fields.Datetime("Resuelto")
    sent_text = fields.Text("Lo que salió")
    resolution = fields.Char("Resultado")
    cost_usd = fields.Float("Costo (US$)", digits=(10, 4))

    @api.depends('create_date')
    def _compute_name(self):
        for rec in self:
            rec.name = f"B{rec.id}" if rec.id else "B"

    @api.depends('partner_id', 'mobile_number')
    def _compute_client(self):
        for rec in self:
            rec.client_id = rec.partner_id.commercial_partner_id
            name = rec.partner_id.name or ''
            company = rec.client_id.name or ''
            if company and name and company != name:
                name = f"{name.split(', ')[-1]} ({company})"
            rec.client_name = name or rec.mobile_number or 'Número sin identificar'

    def _state_label(self):
        self.ensure_one()
        return dict(STATES).get(self.state, self.state).lower()

    # ───────────────────────── entrada ─────────────────────────
    @api.model
    def enqueue_inbound(self, config, wa_message, text, audio=None):
        """Suma un mensaje del cliente a la consulta en curso de ese chat (o abre una)."""
        mm = wa_message.mail_message_id
        channel = self.env['discuss.channel'].sudo().browse(
            mm.res_id if (mm and mm.model == 'discuss.channel') else 0).exists()
        domain = [('state', '=', 'collecting')]
        domain += [('channel_id', '=', channel.id)] if channel else \
            [('mobile_number', '=', wa_message.mobile_number)]
        draft = self.sudo().search(domain, limit=1)
        now = fields.Datetime.now()
        if draft:
            draft.write({'incoming_text': ((draft.incoming_text or '') + '\n' + text).strip(),
                         'last_inbound_at': now})
        else:
            partner = cc.resolve_partner(
                self.env, channel.whatsapp_partner_id if channel else False,
                wa_message.mobile_number)
            draft = self.sudo().create({
                'channel_id': channel.id or False,
                'wa_account_id': wa_message.wa_account_id.id,
                'partner_id': partner.id or False,
                'mobile_number': wa_message.mobile_number,
                'incoming_text': text, 'last_inbound_at': now,
            })
        if audio:
            draft.audio_attachment_ids = [(4, audio.id)]
        draft._trigger_cron(seconds=(config.client_draft_wait_seconds or 0) + 1)
        return draft

    @api.model
    def mark_handled_by_phone(self, channel):
        """Joaco contestó desde el celular en ese chat: lo que esperaba ya no hace falta."""
        drafts = self.sudo().search([('channel_id', '=', channel.id),
                                     ('state', 'in', OPEN_STATES)])
        for draft in drafts:
            draft._close('handled', "Se contestó desde el celular.", keep_order=True)
        return drafts

    def _close(self, state, resolution, keep_order=False):
        """Cierra el borrador sin enviar. La cotización que se había armado se cancela,
        salvo cuando una persona tomó el chat (ahí le sirve tenerla cargada)."""
        self.ensure_one()
        order = self.order_id
        if order and not keep_order and order.state == 'draft':
            try:
                order.sudo().with_context(disable_cancel_warning=True).action_cancel()
            except Exception:  # noqa: BLE001
                _logger.exception("Borradores de empresas: no pude cancelar %s", order.name)
        self.write({'state': state, 'resolved_at': fields.Datetime.now(),
                    'resolution': (resolution or '')[:250]})
        self.activity_ids.action_done()

    def _discard(self, resolution):
        self._close('discarded', resolution)

    def _transcribe_audios(self, config):
        """Suma al texto las notas de voz del cliente (OpenAI, fuera del webhook)."""
        self.ensure_one()
        audios, lines = self.audio_attachment_ids, []
        if not audios:
            return
        key = self.env['cristal.agent.config'].sudo().get_openai_key()
        for att in audios:
            text = None
            if config.enable_audio_transcription and key:
                try:
                    from ..services.transcription import transcribe_audio_attachment
                    text = transcribe_audio_attachment(
                        att, key, model=config.transcription_model or 'gpt-4o-transcribe',
                        language=config.transcription_language or 'es')
                except Exception:  # noqa: BLE001
                    _logger.exception("Borradores de empresas: no pude transcribir %s", att.id)
            lines.append("[nota de voz] " + text if text else
                         "[mandó una nota de voz que no se pudo transcribir: escuchala]")
        self.write({'incoming_text': '\n'.join(t for t in [self.incoming_text] + lines if t),
                    'audio_attachment_ids': [(5, 0, 0)]})

    def _trigger_cron(self, seconds=1):
        cron = self.env.ref('cristal_agent.cron_client_draft', raise_if_not_found=False)
        if cron:
            try:
                cron.sudo()._trigger(at=fields.Datetime.now() + timedelta(seconds=seconds))
            except Exception as e:  # noqa: BLE001
                _logger.warning("Borradores de empresas: no pude programar el cron: %s", e)

    @api.model
    def cron_maintenance(self):
        """Cada 30 min: corre el autotest que pidió una actualización y deja el resultado."""
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not (config.client_draft_selftest_log or '').startswith('pendiente'):
            return
        try:
            results = self.sudo().run_selftest()
            ok = sum(1 for r in results if r[1])
            lines = [f"{fields.Datetime.now():%Y-%m-%d %H:%M} UTC — {ok}/{len(results)} bien"]
            lines += [f"FALLA: {name} — {detail}" for name, good, detail in results if not good]
            log = '\n'.join(lines)
        except Exception as e:  # noqa: BLE001
            log = f"{fields.Datetime.now():%Y-%m-%d %H:%M} UTC — el autotest no corrió: {e}"
        config.write({'client_draft_selftest_log': log})

    # ───────────────────────── cron ─────────────────────────
    @api.model
    def cron_process(self):
        """Arma los borradores de las ráfagas que ya se callaron y aplica las correcciones."""
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not cc.is_enabled(config):
            return
        limit = fields.Datetime.now() - timedelta(seconds=config.client_draft_wait_seconds or 0)
        todo = self.sudo().search([
            '|', ('state', '=', 'correcting'),
            '&', ('state', '=', 'collecting'), ('last_inbound_at', '<=', limit)], order='id')
        for draft in todo:
            try:
                if draft.state == 'correcting':
                    draft._apply_correction(config)
                else:
                    draft._prepare(config)
                if pc._test(self.env) is None:
                    self.env.cr.commit()
            except Exception as e:  # noqa: BLE001
                if pc._test(self.env) is not None:
                    raise
                self.env.cr.rollback()
                _logger.exception("Borradores de empresas: falló %s", draft.name)
                try:
                    draft.write({'state': 'error', 'resolution': str(e)[:200],
                                 'resolved_at': fields.Datetime.now()})
                    self.env.cr.commit()
                except Exception:  # noqa: BLE001
                    self.env.cr.rollback()

    def _human_took_over(self, config):
        """True si una persona escribió en este chat (desde Odoo o desde el celular) hace poco."""
        self.ensure_one()
        if not self.channel_id:
            return False
        hours = config.client_draft_quiet_hours
        if not hours:
            return False
        bot = config.bot_partner_id.id or 2
        msgs = self.env['mail.message'].sudo().search([
            ('model', '=', 'discuss.channel'), ('res_id', '=', self.channel_id.id),
            ('message_type', '=', 'whatsapp_message'),
            ('author_id', 'not in', [bot, self.channel_id.whatsapp_partner_id.id or 0]),
            ('date', '>=', fields.Datetime.now() - timedelta(hours=hours))])
        return bool(msgs.filtered(lambda m: m.author_id.user_ids))

    def _prepare(self, config):
        self.ensure_one()
        older = self.sudo().search([('id', '!=', self.id), ('state', 'in', ('pending', 'correcting')),
                                    ('channel_id', '=', self.channel_id.id)]) \
            if self.channel_id else self.browse()
        if self._human_took_over(config):
            for rec in (self | older):
                rec._close('handled', "Una persona escribió en el chat: no se armó borrador.",
                           keep_order=True)
            return
        if older:
            # Lo nuevo reemplaza al borrador que esperaba: se responde todo junto.
            self.incoming_text = '\n'.join(
                t for t in (older.sorted('id').mapped('incoming_text') + [self.incoming_text]) if t)
            for rec in older:
                rec._close('superseded', f"Reemplazado por {self.name}.")
        self._transcribe_audios(config)
        verdict, products = cc.build_draft(self.env, config, self)
        text = (verdict.get('borrador') or '').strip()
        kind = verdict.get('tipo') if verdict.get('tipo') in dict(cc.KINDS) else 'otro'
        self.write({'kind': kind, 'note': (verdict.get('nota') or '')[:250] or False})
        if not verdict.get('responder') or not text:
            self.write({'state': 'no_reply', 'draft_text': text or False,
                        'resolved_at': fields.Datetime.now(),
                        'resolution': "El mensaje no pide respuesta."})
            return
        self.draft_text = text
        if kind == 'pedido':
            self._build_order(config, verdict, products)
        self._ask_owner(config)

    def _build_order(self, config, verdict, products):
        """Deja una cotización en borrador con los renglones reconocidos. Copia cliente,
        direcciones, lista de precios y posición fiscal del último pedido de la cuenta."""
        self.ensure_one()
        matched, unknown = cc.split_items(verdict, products)
        self.unmatched_text = '\n'.join(unknown) or False
        company = self.client_id
        if not matched or not company:
            return
        SO = self.env['sale.order'].sudo()
        last = SO.search([('partner_id', 'child_of', company.id),
                          ('state', 'in', ('sale', 'done'))], order='date_order desc', limit=1)
        if not last:
            return
        owner = cc.owner_user(config)
        vals = {
            'partner_id': last.partner_id.id,
            'partner_invoice_id': last.partner_invoice_id.id,
            'partner_shipping_id': last.partner_shipping_id.id,
            'pricelist_id': last.pricelist_id.id,
            'fiscal_position_id': last.fiscal_position_id.id or False,
            'payment_term_id': last.payment_term_id.id or False,
            'team_id': last.team_id.id or False,
            'user_id': owner.id or last.user_id.id,
            'origin': f"WhatsApp empresas {self.name}",
            'order_line': [(0, 0, {'product_id': p.id, 'product_uom_qty': q})
                           for p, q in matched],
        }
        order = SO.with_context(from_cristal_agent=True, mail_create_nosubscribe=True).create(vals)
        body = _("Cotización armada desde el WhatsApp de empresas (%s). El cliente escribió:") % self.name
        body += "<br/>" + pc._escape(self.incoming_text or '').replace('\n', '<br/>')
        if unknown:
            body += "<br/><b>" + _("Sin identificar (no se cargó):") + "</b><br/>" + \
                    "<br/>".join(pc._escape(u) for u in unknown)
        try:
            from markupsafe import Markup
            order.message_post(body=Markup(body), subtype_xmlid='mail.mt_note')
        except Exception:  # noqa: BLE001
            _logger.exception("Borradores de empresas: no pude dejar la nota en %s", order.name)
        self.order_id = order.id

    def _ask_owner(self, config, corrected=False):
        self.ensure_one()
        via, mail_id = 'screen', False
        if self.kind in cc.NOTIFY_KINDS and config.client_draft_notify_whatsapp:
            ok, mail_id = cc.tell_owner(self.env, config, cc.owner_text(self, corrected))
            if ok:
                via = 'whatsapp'
        self.write({'state': 'pending', 'asked_at': fields.Datetime.now(),
                    'notify_via': via, 'notify_mail_message_id': mail_id or False,
                    'correction_text': False})

    def _apply_correction(self, config):
        self.ensure_one()
        verdict, _products = cc.build_draft(self.env, config, self,
                                            correction=self.correction_text)
        text = (verdict.get('borrador') or '').strip()
        if not text:
            self.write({'state': 'pending', 'correction_text': False})
            cc.tell_owner(self.env, config, f"No pude aplicar la corrección a {self.name}. "
                                            f"Mandámela de nuevo o contestale vos.")
            return
        self.draft_text = text
        self._ask_owner(config, corrected=True)

    # ───────────────────────── salida ─────────────────────────
    def send_to_client(self):
        """Manda el borrador al cliente. Solo se llama con el OK de Joaco."""
        self.ensure_one()
        config = self.env['cristal.agent.config'].sudo().get_active()
        self._check_admin(also=cc.owner_user(config))
        if self.state != 'pending':
            raise UserError(_("%s ya no está esperando el OK.") % self.name)
        text = (self.draft_text or '').strip()
        if not text:
            raise UserError(_("El borrador está vacío."))
        account = self.wa_account_id or config.client_draft_wa_account_id
        by_whatsapp = self.notify_via == 'whatsapp'
        if pc._test(self.env) is None and not pc._window_open(
                self.env, account, self.mobile_number):
            self.write({'state': 'error', 'resolved_at': fields.Datetime.now(),
                        'resolution': "Pasaron más de 24 h desde el último mensaje del cliente."})
            if by_whatsapp:
                cc.tell_owner(self.env, config,
                              f"{self.name} NO salió: pasaron más de 24 h desde el último "
                              f"mensaje de {self.client_name}. Contestale desde el celular.")
            return False
        res = pc.wa_send(self.env, self.channel_id, account, self.mobile_number, text)
        now = fields.Datetime.now()
        if not res.get('ok'):
            self.write({'state': 'error', 'resolved_at': now,
                        'resolution': ("No salió: " + (res.get('error') or ''))[:250]})
            if by_whatsapp:
                cc.tell_owner(self.env, config,
                              f"{self.name} NO salió a {self.client_name}: "
                              f"{res.get('error') or 'error de WhatsApp'}. Contestale vos.")
            return False
        self.write({'state': 'sent', 'resolved_at': now, 'sent_text': text,
                    'resolution': "Enviado con el OK de Joaco."})
        self.activity_ids.action_done()
        if by_whatsapp:
            cc.tell_owner(self.env, config, f"Enviado a {self.client_name} ({self.name}).")
        return True

    def action_send(self):
        """Botón en Odoo: mismo efecto que el «dale» por WhatsApp."""
        for rec in self:
            rec.send_to_client()
        return True

    def action_discard(self):
        for rec in self.filtered(lambda r: r.state in OPEN_STATES):
            rec._discard(f"Descartado en Odoo por {self.env.user.name}.")
        return True

    def action_open_order(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'sale.order',
                'res_id': self.order_id.id, 'view_mode': 'form', 'target': 'current'}

    def action_open_chat(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'mail.action_discuss',
                'params': {'active_id': f"discuss.channel_{self.channel_id.id}"}}

    def _check_admin(self, also=None):
        user = self.env.user
        if not (self.env.su or user.has_group('base.group_system') or (also and user == also)):
            raise AccessError(_("Solo Joaco o un administrador puede hacer esto."))

    # ───────────────────────── prueba sin enviar ─────────────────────────
    @api.model
    def preview_draft(self, mobile_number, text):
        """Arma el borrador que saldría para ese celular y ese texto, con el contexto real y
        una llamada real a Claude. No guarda nada y no manda nada."""
        self._check_admin()
        env = self.env(su=True)
        config = env['cristal.agent.config'].get_active()
        account = config.client_draft_wa_account_id
        out = {}
        try:
            with env.cr.savepoint():
                channel = pc._channel_for(env, account, mobile_number) if account else \
                    env['discuss.channel']
                partner = cc.resolve_partner(
                    env, channel.whatsapp_partner_id if channel else False, mobile_number)
                draft = env['cristal.agent.client.draft'].create({
                    'channel_id': channel.id or False, 'wa_account_id': account.id or False,
                    'partner_id': partner.id or False,
                    'mobile_number': mobile_number, 'incoming_text': text,
                    'last_inbound_at': fields.Datetime.now()})
                verdict, products = cc.build_draft(env, config, draft)
                matched, unknown = cc.split_items(verdict, products)
                out = {'quien': draft.client_name, 'tipo': verdict.get('tipo'),
                       'responder': bool(verdict.get('responder')),
                       'borrador': verdict.get('borrador') or '',
                       'nota': verdict.get('nota') or '',
                       'pedido': [f"{q:g} x {p.display_name}" for p, q in matched],
                       'sin_identificar': unknown,
                       'contexto': cc.client_context(env, draft)[0],
                       'costo_usd': draft.cost_usd}
                raise _SelftestRollback()
        except _SelftestRollback:
            pass
        return out

    # ───────────────────────── autotest ─────────────────────────
    @api.model
    def action_selftest(self):
        results = self.sudo().run_selftest()
        bad = [f"✗ {name}: {detail}" for name, ok, detail in results if not ok]
        good = sum(1 for r in results if r[1])
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': f"Autotest de borradores de empresas: {good}/{len(results)} bien",
            'message': '\n'.join(bad) or "Todo bien. No se mandó ni se guardó nada.",
            'type': 'danger' if bad else 'success', 'sticky': bool(bad)}}

    @api.model
    def run_selftest(self):
        """Prueba el circuito completo sin red y sin dejar nada guardado.
        Devuelve [(caso, ok, detalle)]."""
        self._check_admin()
        results = []

        def check(name, ok, detail=''):
            results.append((name, bool(ok), '' if ok else str(detail)[:300]))

        box = {'draft': 'Perfecto, ya lo paso. Gracias!', 'sent': [], 'owner': []}
        env = self.env(su=True, context=dict(self.env.context, **{pc.TEST_CTX: box}))
        try:
            with env.cr.savepoint():
                Draft = env['cristal.agent.client.draft']
                WA = env['whatsapp.message']
                config = env['cristal.agent.config'].get_active()
                account = env['whatsapp.account'].search([], order='id desc', limit=1)
                owner = config.owner_user_id or env.ref('base.user_admin')
                config.write({'client_draft_enabled': True,
                              'client_draft_wa_account_id': account.id,
                              'client_draft_owner_user_id': owner.id,
                              'client_draft_wait_seconds': 0,
                              'client_draft_quiet_hours': 2,
                              'client_draft_notify_whatsapp': True,
                              'owner_whatsapp_number': '3580000009'})
                company = env['res.partner'].create({'name': 'Empresa Autotest', 'is_company': True})
                contact = env['res.partner'].create({
                    'name': 'Compras Autotest', 'parent_id': company.id,
                    'mobile': '+5493580000002'})
                prod = env['product.product'].create({
                    'name': 'Detergente autotest 5 L', 'list_price': 1000.0, 'sale_ok': True})
                old = env['sale.order'].create({
                    'partner_id': contact.id,
                    'order_line': [(0, 0, {'product_id': prod.id, 'product_uom_qty': 2})]})
                old.write({'state': 'sale', 'date_order': fields.Datetime.now() - timedelta(days=20)})
                channel = env['discuss.channel'].create({
                    'name': 'Autotest empresas', 'channel_type': 'whatsapp',
                    'wa_account_id': account.id, 'whatsapp_number': '5493580000002',
                    'whatsapp_partner_id': contact.id})

                def inbound(text, number='+5493580000002', chan=None, parent=None):
                    chan = chan or channel
                    vals = {'author_id': contact.id, 'body': f"<p>{text}</p>",
                            'message_type': 'whatsapp_message', 'model': 'discuss.channel',
                            'res_id': chan.id}
                    if parent:
                        vals['parent_id'] = parent
                    mm = env['mail.message'].with_context(from_cristal_agent=True).create(vals)
                    return WA.with_context(from_cristal_agent=True).new({
                        'mail_message_id': mm.id, 'wa_account_id': chan.wa_account_id.id,
                        'mobile_number': number, 'message_type': 'inbound', 'state': 'received'})

                def client_says(text):
                    msg = inbound(text)
                    WA._client_consult_inbound(config, msg, text, msg.mobile_number)
                    Draft.cron_process()
                    return Draft.search([('channel_id', '=', channel.id)], order='id desc', limit=1)

                # 1) Consulta: borrador pendiente, solo en pantalla (sin WhatsApp a Joaco).
                box.update(tipo='consulta', items=[])
                d1 = client_says("Hola, tienen cera para pisos de goma?")
                check("consulta: queda esperando el OK", d1.state == 'pending', d1.state)
                check("consulta: no le suena el teléfono a Joaco",
                      d1.notify_via == 'screen' and not box['owner'], (d1.notify_via, box['owner']))
                check("nada sale al cliente sin OK", not box['sent'], box['sent'])
                d1.action_send()
                check("botón Enviar: sale el borrador", d1.state == 'sent'
                      and box['sent'] and box['sent'][-1]['text'] == box['draft'], d1.state)

                # 2) Pedido: cotización en borrador con lo reconocido y aviso a Joaco.
                box['sent'].clear()
                box.update(tipo='pedido', items=[
                    {'texto': '3 detergentes', 'cantidad': 3, 'product_id': prod.id},
                    {'texto': '2 cosas raras', 'cantidad': 2, 'product_id': None},
                    {'texto': 'producto ajeno', 'cantidad': 1, 'product_id': 999999999}])
                d2 = client_says("Te paso pedido: 3 detergentes, 2 cosas raras")
                order = d2.order_id
                check("pedido: arma la cotización en borrador",
                      order and order.state == 'draft' and len(order.order_line) == 1
                      and order.order_line.product_uom_qty == 3, order and order.state)
                check("pedido: copia el cliente del último pedido",
                      order and order.partner_id == contact, order and order.partner_id.name)
                check("pedido: lo que no reconoce queda marcado y no se carga",
                      'cosas raras' in (d2.unmatched_text or '')
                      and 'producto ajeno' in (d2.unmatched_text or ''), d2.unmatched_text)
                check("pedido: le avisa a Joaco por WhatsApp",
                      d2.notify_via == 'whatsapp' and box['owner']
                      and d2.name in box['owner'][-1], (d2.notify_via, box['owner'][-1:]))

                # 3) Joaco contesta "no" con el código: se descarta y se cancela la cotización.
                owner_msg = inbound("no", number='+5493580000009')
                handled = cc.handle_owner_message(env, config, owner_msg, f"{d2.name} no")
                check("«no» de Joaco: descarta y cancela la cotización",
                      handled and d2.state == 'discarded' and order.state == 'cancel'
                      and not box['sent'], (handled, d2.state, order.state))

                # 4) Corrección y después "dale".
                d3 = client_says("Sumame 3 detergentes")
                owner_msg = inbound("x", number='+5493580000009')
                cc.handle_owner_message(env, config, owner_msg,
                                        f"{d3.name} decile que mañana a la mañana")
                check("corrección: queda en cola", d3.state == 'correcting', d3.state)
                box['draft'] = 'Perfecto, mañana a la mañana te llega.'
                Draft.cron_process()
                check("corrección: vuelve a esperar el OK con el texto nuevo",
                      d3.state == 'pending' and d3.draft_text == box['draft'], d3.state)
                cc.handle_owner_message(env, config, owner_msg, f"{d3.name} dale")
                check("«dale»: sale el corregido y la cotización sigue en borrador",
                      d3.state == 'sent' and box['sent'][-1]['text'] == box['draft']
                      and d3.order_id.state == 'draft', (d3.state, d3.order_id.state))

                # 5) Un "ok" suelto de Joaco sin borradores esperando no se toma.
                if not cc._pending(env):
                    check("«ok» sin borradores esperando: sigue su camino",
                          cc.handle_owner_message(env, config, owner_msg, "ok") is False)

                # 6) "Gracias" no pide respuesta.
                box.update(tipo='otro', items=[], responder=False)
                d4 = client_says("Gracias!!")
                check("«gracias»: no arma consulta", d4.state == 'no_reply', d4.state)
                box['responder'] = True

                # 7) Mensaje nuevo reemplaza al borrador que esperaba.
                box.update(tipo='consulta')
                d5 = client_says("Tienen lavandina?")
                d6 = client_says("Y detergente?")
                check("mensaje nuevo: reemplaza al que esperaba",
                      d5.state == 'superseded' and d6.state == 'pending'
                      and 'lavandina' in d6.incoming_text, (d5.state, d6.state))

                # 8) Joaco contesta desde el celular: el borrador se da por atendido.
                Draft.mark_handled_by_phone(channel)
                check("contestó desde el celular: borrador atendido", d6.state == 'handled', d6.state)

                # 9) Una persona escribió en el chat: por un rato no se arman borradores.
                env['mail.message'].with_context(from_cristal_agent=True).create({
                    'author_id': owner.partner_id.id, 'body': '<p>Ahí te lo mando</p>',
                    'message_type': 'whatsapp_message', 'model': 'discuss.channel',
                    'res_id': channel.id})
                d7 = client_says("Dale, gracias. Otra consulta, tienen trapos?")
                check("una persona escribió: no se arma borrador", d7.state == 'handled', d7.state)

                # 10) Apagado: no registra nada.
                config.client_draft_enabled = False
                before = Draft.search_count([])
                msg = inbound("Hola")
                check("apagado: la cuenta no se toma",
                      not cc.is_client_message(config, msg) and Draft.search_count([]) == before)
                raise _SelftestRollback()
        except _SelftestRollback:
            pass
        except Exception as e:  # noqa: BLE001
            _logger.exception("Autotest borradores de empresas")
            results.append(("el autotest corrió entero", False, str(e)[:300]))
        return results
