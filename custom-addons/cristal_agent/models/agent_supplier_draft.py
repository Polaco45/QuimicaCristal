# -*- coding: utf-8 -*-
"""v1.77 — Borradores de respuesta a proveedores (modo consulta de Compras).

Cada registro es una consulta: lo que escribió el proveedor, el borrador y qué decidió
Sergio. Ver services/purchase_consult.py.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

STATES = [
    ('collecting', 'Juntando mensajes'),
    ('pending', 'Esperando el OK'),
    ('correcting', 'Aplicando corrección'),
    ('sent', 'Enviado'),
    ('discarded', 'Descartado'),
    ('superseded', 'Reemplazado por otro'),
    ('no_reply', 'No pide respuesta'),
    ('handled', 'Lo atendió una persona'),
    ('error', 'No se pudo'),
]


class CristalAgentSupplierDraft(models.Model):
    _name = 'cristal.agent.supplier.draft'
    _description = "Cristal Agent — borrador de respuesta a proveedor"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char("Código", compute='_compute_name', store=True)
    state = fields.Selection(STATES, "Estado", default='collecting', required=True,
                             index=True, tracking=True)
    channel_id = fields.Many2one('discuss.channel', "Chat", ondelete='set null', index=True)
    wa_account_id = fields.Many2one('whatsapp.account', "Cuenta de WhatsApp")
    partner_id = fields.Many2one('res.partner', "Contacto", ondelete='set null')
    supplier_id = fields.Many2one('res.partner', "Proveedor", ondelete='set null',
                                  compute='_compute_supplier', store=True)
    supplier_name = fields.Char("Quién escribió", compute='_compute_supplier', store=True)
    mobile_number = fields.Char("Celular")
    incoming_text = fields.Text("Qué escribió")
    last_inbound_at = fields.Datetime("Último mensaje")
    draft_text = fields.Text("Borrador")
    note = fields.Char("Nota para Sergio")
    correction_text = fields.Text("Corrección pedida")
    asked_at = fields.Datetime("Consultado a Sergio")
    notify_via = fields.Selection([('whatsapp', 'WhatsApp'),
                                   ('template', 'WhatsApp (plantilla)'),
                                   ('odoo', 'Actividad en Odoo')], "Aviso por")
    audio_attachment_ids = fields.Many2many(
        'ir.attachment', 'cristal_supplier_draft_audio_rel', 'draft_id', 'attachment_id',
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
            rec.name = f"C{rec.id}" if rec.id else "C"

    @api.depends('partner_id', 'mobile_number')
    def _compute_supplier(self):
        for rec in self:
            rec.supplier_id = rec.partner_id.commercial_partner_id
            rec.supplier_name = (rec.supplier_id.name or rec.partner_id.name
                                 or rec.mobile_number or 'Número sin identificar')

    def _state_label(self):
        self.ensure_one()
        return dict(STATES).get(self.state, self.state).lower()

    # ───────────────────────── entrada ─────────────────────────
    @api.model
    def enqueue_inbound(self, config, wa_message, text, audio=None):
        """Suma un mensaje de proveedor a la consulta en curso de ese chat (o abre una)."""
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
            partner = channel.whatsapp_partner_id if channel else self.env['res.partner']
            draft = self.sudo().create({
                'channel_id': channel.id or False,
                'wa_account_id': wa_message.wa_account_id.id,
                'partner_id': partner.id or False,
                'mobile_number': wa_message.mobile_number,
                'incoming_text': text, 'last_inbound_at': now,
            })
        if audio:
            draft.audio_attachment_ids = [(4, audio.id)]
        draft._trigger_cron(seconds=(config.debounce_seconds or 0) + 1)
        return draft

    @api.model
    def mark_handled_by_phone(self, channel):
        """Sergio contestó desde el celular en ese chat: lo que esperaba ya no hace falta."""
        drafts = self.sudo().search([('channel_id', '=', channel.id),
                                     ('state', 'in', ('collecting', 'pending', 'correcting'))])
        if drafts:
            drafts.write({'state': 'handled', 'resolved_at': fields.Datetime.now(),
                          'resolution': "Se contestó desde el celular."})
            drafts.activity_ids.action_done()
        return drafts

    def _transcribe_audios(self, config):
        """Suma al texto las notas de voz del proveedor (OpenAI, fuera del webhook)."""
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
                    _logger.exception("Compras consulta: no pude transcribir el audio %s", att.id)
            lines.append("[nota de voz] " + text if text else
                         "[mandó una nota de voz que no se pudo transcribir: escuchala]")
        self.write({'incoming_text': '\n'.join(t for t in [self.incoming_text] + lines if t),
                    'audio_attachment_ids': [(5, 0, 0)]})

    @api.model
    def cron_maintenance(self):
        """Cada 30 min: plantilla a Meta (si falta) y autotest pedido por una actualización."""
        self.cron_submit_template()
        config = self.env['cristal.agent.config'].sudo().get_active()
        if (config.purchase_selftest_log or '').startswith('pendiente'):
            try:
                results = self.sudo().run_selftest()
                ok = sum(1 for r in results if r[1])
                lines = [f"{fields.Datetime.now():%Y-%m-%d %H:%M} UTC — {ok}/{len(results)} bien"]
                lines += [f"FALLA: {name} — {detail}" for name, good, detail in results if not good]
                log = '\n'.join(lines)
            except Exception as e:  # noqa: BLE001
                log = f"{fields.Datetime.now():%Y-%m-%d %H:%M} UTC — el autotest no corrió: {e}"
            config.write({'purchase_selftest_log': log})

    @api.model
    def cron_submit_template(self):
        """Manda a aprobar a Meta la plantilla de aviso a Sergio. Solo en producción y solo
        mientras esté en borrador (una vez enviada, no hace nada)."""
        from ..services import purchase_consult as pc
        config = self.env['cristal.agent.config'].sudo().get_active()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        if not config.purchase_wa_account_id or '.dev.odoo.com' in base_url:
            return False
        template = pc.ensure_purchase_template(self.env, config.purchase_wa_account_id)
        if not template or template.status != 'draft' or template.wa_template_uid:
            return False
        try:
            template.button_submit_template()
            _logger.info("Plantilla %s enviada a Meta: %s", template.template_name, template.status)
        except Exception as e:  # noqa: BLE001
            _logger.warning("No pude mandar a Meta la plantilla de Compras: %s", e)
            return False
        return True

    def _trigger_cron(self, seconds=1):
        cron = self.env.ref('cristal_agent.cron_purchase_consult', raise_if_not_found=False)
        if cron:
            try:
                cron.sudo()._trigger(at=fields.Datetime.now() + timedelta(seconds=seconds))
            except Exception as e:  # noqa: BLE001
                _logger.warning("Compras consulta: no pude programar el cron: %s", e)

    # ───────────────────────── cron ─────────────────────────
    @api.model
    def cron_process(self):
        """Arma los borradores de las ráfagas que ya se callaron y aplica las correcciones."""
        from ..services import purchase_consult as pc
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not pc.is_enabled(config):
            return
        limit = fields.Datetime.now() - timedelta(seconds=config.debounce_seconds or 0)
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
                _logger.exception("Compras consulta: falló %s", draft.name)
                try:
                    draft.write({'state': 'error', 'resolution': str(e)[:200],
                                 'resolved_at': fields.Datetime.now()})
                    pc.tell_owner(self.env, config,
                                  f"Compras {draft.name} · {draft.supplier_name} escribió y no "
                                  f"pude armar el borrador. Contestale vos.", draft=draft)
                    self.env.cr.commit()
                except Exception:  # noqa: BLE001
                    self.env.cr.rollback()

    def _human_took_over(self, config):
        """True si una persona escribió en este chat desde Odoo en las últimas horas."""
        self.ensure_one()
        if not self.channel_id:
            return False
        hours = config.human_takeover_hours or 12
        bot = config.bot_partner_id.id or 2
        msgs = self.env['mail.message'].sudo().search([
            ('model', '=', 'discuss.channel'), ('res_id', '=', self.channel_id.id),
            ('message_type', '=', 'whatsapp_message'),
            ('author_id', 'not in', [bot, self.channel_id.whatsapp_partner_id.id or 0]),
            ('date', '>=', fields.Datetime.now() - timedelta(hours=hours))])
        return bool(msgs.filtered(lambda m: m.author_id.user_ids))

    def _prepare(self, config):
        from ..services import purchase_consult as pc
        self.ensure_one()
        now = fields.Datetime.now()
        older = self.sudo().search([('id', '!=', self.id), ('state', 'in', ('pending', 'correcting')),
                                    ('channel_id', '=', self.channel_id.id)]) \
            if self.channel_id else self.browse()
        if self._human_took_over(config):
            (self | older).write({'state': 'handled', 'resolved_at': now,
                                  'resolution': "Una persona escribió en el chat: no se armó borrador."})
            return
        if older:
            # Lo nuevo reemplaza al borrador que esperaba: se responde todo junto.
            self.incoming_text = '\n'.join(
                t for t in (older.sorted('id').mapped('incoming_text') + [self.incoming_text]) if t)
            older.write({'state': 'superseded', 'resolved_at': now,
                         'resolution': f"Reemplazado por {self.name}."})
        self._transcribe_audios(config)
        verdict = pc.build_draft(self.env, config, self)
        text = (verdict.get('borrador') or '').strip()
        self.note = (verdict.get('nota') or '')[:250] or False
        if not verdict.get('responder') or not text:
            self.write({'state': 'no_reply', 'draft_text': text or False, 'resolved_at': now,
                        'resolution': "El mensaje no pide respuesta: no se consultó a Sergio."})
            return
        self.draft_text = text
        self._ask_owner(config)

    def _ask_owner(self, config, corrected=False):
        from ..services import purchase_consult as pc
        self.ensure_one()
        via, mail_id = pc.tell_owner(self.env, config, pc.owner_text(self, corrected), draft=self,
                                     template_text=pc.owner_template_text(self))
        self.write({'state': 'pending', 'asked_at': fields.Datetime.now(),
                    'notify_via': via or False, 'notify_mail_message_id': mail_id or False,
                    'correction_text': False})
        if not via:
            _logger.warning("Compras consulta: %s quedó esperando sin poder avisarle a Sergio",
                            self.name)

    def _apply_correction(self, config):
        from ..services import purchase_consult as pc
        self.ensure_one()
        verdict = pc.build_draft(self.env, config, self, correction=self.correction_text)
        text = (verdict.get('borrador') or '').strip()
        if not text:
            self.state = 'pending'
            pc.tell_owner(self.env, config, f"No pude aplicar la corrección a {self.name}. "
                                            f"Mandámela de nuevo o contestale vos.", draft=self)
            return
        self.draft_text = text
        if config.purchase_correction_direct:
            self.state = 'pending'
            self.send_to_supplier()
        else:
            self._ask_owner(config, corrected=True)

    # ───────────────────────── salida ─────────────────────────
    def send_to_supplier(self):
        """Manda el borrador al proveedor. Solo se llama con el OK de Sergio."""
        from ..services import purchase_consult as pc
        self.ensure_one()
        config = self.env['cristal.agent.config'].sudo().get_active()
        self._check_admin(also=config.purchase_owner_user_id)
        if self.state != 'pending':
            raise UserError(_("%s ya no está esperando el OK.") % self.name)
        text = (self.draft_text or '').strip()
        if not text:
            raise UserError(_("El borrador está vacío."))
        account = self.wa_account_id or config.purchase_wa_account_id
        if pc._test(self.env) is None and not pc._window_open(
                self.env, account, self.mobile_number):
            self.write({'state': 'error', 'resolved_at': fields.Datetime.now(),
                        'resolution': "Pasaron más de 24 h desde el último mensaje del proveedor."})
            pc.tell_owner(self.env, config,
                          f"{self.name} NO salió: pasaron más de 24 h desde el último mensaje "
                          f"de {self.supplier_name} y WhatsApp ya no deja mandar texto libre. "
                          f"Contestale desde el celular.", draft=self)
            return False
        res = pc.wa_send(self.env, self.channel_id, account, self.mobile_number, text)
        now = fields.Datetime.now()
        if not res.get('ok'):
            self.write({'state': 'error', 'resolved_at': now,
                        'resolution': ("No salió: " + (res.get('error') or ''))[:250]})
            pc.tell_owner(self.env, config,
                          f"{self.name} NO salió a {self.supplier_name}: "
                          f"{res.get('error') or 'error de WhatsApp'}. Contestale vos.", draft=self)
            return False
        self.write({'state': 'sent', 'resolved_at': now, 'sent_text': text,
                    'resolution': "Enviado con el OK de Sergio."})
        self.activity_ids.action_done()
        pc.tell_owner(self.env, config, f"Enviado a {self.supplier_name} ({self.name}).")
        return True

    def action_send(self):
        """Botón en Odoo: mismo efecto que el «dale» por WhatsApp."""
        for rec in self:
            rec.send_to_supplier()
        return True

    def action_discard(self):
        for rec in self.filtered(lambda r: r.state in ('pending', 'collecting', 'correcting')):
            rec.write({'state': 'discarded', 'resolved_at': fields.Datetime.now(),
                       'resolution': f"Descartado en Odoo por {self.env.user.name}."})
            rec.activity_ids.action_done()
        return True

    def _check_admin(self, also=None):
        """Mandar, probar o previsualizar: solo el sistema, un administrador o el responsable."""
        user = self.env.user
        if not (self.env.su or user.has_group('base.group_system') or (also and user == also)):
            raise AccessError(_("Solo el responsable de Compras o un administrador puede hacer esto."))

    @api.model
    def preview_draft(self, mobile_number, text):
        """Borrador REAL (llama a Claude) para lo que escribiría ese número, con su contexto
        de Odoo. No guarda ni manda nada: sirve para revisar la calidad antes de prender."""
        from ..services import purchase_consult as pc
        self._check_admin()
        env = self.env(su=True)
        config = env['cristal.agent.config'].get_active()
        account = config.purchase_wa_account_id
        out = {}
        try:
            with env.cr.savepoint():
                channel = pc._channel_for(env, account, mobile_number)
                partner = channel.whatsapp_partner_id
                if not partner:
                    tail = pc.digits(mobile_number)[-10:]
                    partner = env['res.partner'].search(
                        ['|', ('mobile', 'like', tail[-8:]), ('phone', 'like', tail[-8:])],
                        limit=1) if len(tail) == 10 else partner
                draft = env[self._name].create({
                    'channel_id': channel.id or False, 'wa_account_id': account.id,
                    'partner_id': partner.id or False, 'mobile_number': mobile_number,
                    'incoming_text': text, 'last_inbound_at': fields.Datetime.now()})
                out = dict(pc.build_draft(env, config, draft) or {})
                out['contexto'] = pc.supplier_context(env, draft)
                out['historial'] = pc.conversation(env, channel)
                out['costo_usd'] = draft.cost_usd
                raise _SelftestRollback()
        except _SelftestRollback:
            pass
        return out

    # ───────────────────────── autotest ─────────────────────────
    @api.model
    def action_selftest(self):
        results = self.run_selftest()
        ok = all(r[1] for r in results)
        lines = '\n'.join(f"{'✅' if good else '❌'} {name}" + (f" — {detail}" if detail else '')
                          for name, good, detail in results)
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': "Autotest Compras: " + ("todo bien" if ok else "HAY FALLAS"),
                       'message': lines, 'sticky': True,
                       'type': 'success' if ok else 'danger'},
        }

    @api.model
    def run_selftest(self):
        """Recorre el circuito completo sin llamar a Claude ni mandar WhatsApp, dentro de
        un savepoint que se revierte: no deja datos."""
        from ..services import purchase_consult as pc
        self._check_admin()
        results = []

        def check(name, cond, detail=''):
            results.append((name, bool(cond), '' if cond else detail))

        box = {'draft': 'Recibido, lo revisamos y te confirmamos.', 'sent': []}
        env = self.env(su=True, context=dict(self.env.context, **{pc.TEST_CTX: box}))
        Draft = env['cristal.agent.supplier.draft']
        try:
            with env.cr.savepoint():
                config = env['cristal.agent.config'].get_active()
                account = config.purchase_wa_account_id or env['whatsapp.account'].search(
                    [('name', 'ilike', 'Compras')], order='id desc', limit=1)
                owner = config.purchase_owner_user_id or env.ref('base.user_admin')
                config.write({'purchase_consult_enabled': True,
                              'purchase_wa_account_id': account.id,
                              'purchase_owner_user_id': owner.id,
                              'purchase_owner_whatsapp_number': '+5493580000001',
                              'purchase_correction_direct': False, 'debounce_seconds': 0})
                check("hay cuenta de WhatsApp de Compras", account, "no encontré la cuenta")
                # Los borradores reales que estén esperando no participan de la prueba.
                Draft.search([('state', 'in', ('collecting', 'pending', 'correcting'))]).write(
                    {'state': 'discarded'})
                supplier = env['res.partner'].create({
                    'name': 'Proveedor Autotest', 'mobile': '+5493580000002', 'supplier_rank': 1})
                runs_before = env['cristal.agent.run'].search_count([])

                def channel_for(partner, number):
                    return env['discuss.channel'].create({
                        'name': partner.name, 'channel_type': 'whatsapp',
                        'whatsapp_number': number.lstrip('+'),
                        'whatsapp_partner_id': partner.id, 'wa_account_id': account.id})

                def inbound(channel, partner, number, text, parent=False):
                    mm = env['mail.message'].with_context(from_cristal_agent=True).create({
                        'author_id': partner.id, 'body': f"<p>{text}</p>",
                        'message_type': 'whatsapp_message', 'model': 'discuss.channel',
                        'res_id': channel.id, 'parent_id': parent or False})
                    return env['whatsapp.message'].create({
                        'mail_message_id': mm.id, 'wa_account_id': account.id,
                        'mobile_number': number, 'message_type': 'inbound',
                        'state': 'received'})

                sup_ch = channel_for(supplier, '+5493580000002')
                own_ch = channel_for(owner.partner_id, '+5493580000001')
                owner_in = lambda text: inbound(own_ch, owner.partner_id, '+5493580000001', text)  # noqa: E731

                # 1) Proveedor escribe → borrador, consulta a Sergio, nada al proveedor.
                inbound(sup_ch, supplier, '+5493580000002', 'Hola, mañana despachamos')
                inbound(sup_ch, supplier, '+5493580000002', '¿Me confirmás la dirección?')
                d1 = Draft.search([('channel_id', '=', sup_ch.id)])
                check("la ráfaga queda en una sola consulta",
                      len(d1) == 1 and d1.state == 'collecting'
                      and 'dirección' in (d1.incoming_text or ''), f"{len(d1)} / {d1.mapped('state')}")
                Draft.cron_process()
                check("se arma el borrador y queda esperando",
                      d1.state == 'pending' and d1.draft_text == box['draft'], d1.state)
                check("la consulta va a Sergio, no al proveedor",
                      len(box['sent']) == 1 and pc.same_number(box['sent'][0]['to'], '+5493580000001')
                      and d1.name in box['sent'][0]['text'], str(box['sent']))
                check("el agente de ventas no intervino",
                      env['cristal.agent.run'].search_count([]) == runs_before
                      and not env['cristal.agent.memory'].search([('partner_id', '=', supplier.id)]),
                      "se creó una corrida o una memoria de ventas")

                # 2) Corrección → borrador nuevo, sigue sin salir.
                box['sent'].clear()
                box['draft'] = 'Texto corregido de prueba.'
                owner_in('pasale la dirección de la planta')
                check("la corrección queda en cola", d1.state == 'correcting', d1.state)
                Draft.cron_process()
                check("la corrección vuelve a Sergio y no sale sola",
                      d1.state == 'pending' and d1.draft_text == box['draft']
                      and len(box['sent']) == 1
                      and pc.same_number(box['sent'][0]['to'], '+5493580000001'), str(box['sent']))

                # 3) "dale" → sale tal cual al proveedor.
                box['sent'].clear()
                owner_in('dale')
                to_sup = [s for s in box['sent'] if pc.same_number(s['to'], '+5493580000002')]
                check("con el dale sale el borrador tal cual",
                      d1.state == 'sent' and len(to_sup) == 1
                      and to_sup[0]['text'] == box['draft'], f"{d1.state} {box['sent']}")

                # 4) "no" → se descarta.
                box['sent'].clear()
                inbound(sup_ch, supplier, '+5493580000002', '¿Y el pago de la factura?')
                Draft.cron_process()
                d2 = Draft.search([('channel_id', '=', sup_ch.id), ('state', '=', 'pending')])
                box['sent'].clear()
                owner_in('no')
                check("con el no se descarta y no sale nada",
                      d2.state == 'discarded'
                      and not [s for s in box['sent'] if pc.same_number(s['to'], '+5493580000002')],
                      d2.state)

                # 5) Dos esperando y un "dale" sin código → pregunta cuál; con código, sale.
                other = env['res.partner'].create({
                    'name': 'Otro Proveedor Autotest', 'mobile': '+5493580000003',
                    'supplier_rank': 1})
                oth_ch = channel_for(other, '+5493580000003')
                inbound(sup_ch, supplier, '+5493580000002', '¿Reciben el lunes?')
                inbound(oth_ch, other, '+5493580000003', '¿Les mando la lista nueva?')
                Draft.cron_process()
                pend = Draft.search([('state', '=', 'pending'),
                                     ('channel_id', 'in', (sup_ch | oth_ch).ids)])
                box['sent'].clear()
                owner_in('dale')
                check("con dos esperando pregunta cuál",
                      len(pend) == 2 and all(p.state == 'pending' for p in pend)
                      and len(box['sent']) == 1 and 'varios' in box['sent'][0]['text'],
                      f"{pend.mapped('state')} {box['sent']}")
                first = pend.filtered(lambda p: p.channel_id == oth_ch)
                box['sent'].clear()
                owner_in(f"{first.name} dale")
                check("con el código sale solo ese",
                      first.state == 'sent' and (pend - first).state == 'pending',
                      f"{first.state} / {(pend - first).state}")

                # 6) Mensaje nuevo del mismo proveedor reemplaza al que esperaba.
                waiting = pend - first
                inbound(sup_ch, supplier, '+5493580000002', 'Perdón, el martes')
                Draft.cron_process()
                newer = Draft.search([('channel_id', '=', sup_ch.id), ('state', '=', 'pending')])
                check("lo nuevo reemplaza al borrador que esperaba",
                      waiting.state == 'superseded' and len(newer) == 1
                      and 'lunes' in newer.incoming_text and 'martes' in newer.incoming_text,
                      f"{waiting.state} / {newer.mapped('incoming_text')}")

                # 7) Una persona escribe en el chat desde Odoo → el agente se corre.
                env['mail.message'].with_context(from_cristal_agent=True).create({
                    'author_id': owner.partner_id.id, 'body': '<p>Te llamo en un rato</p>',
                    'message_type': 'whatsapp_message', 'model': 'discuss.channel',
                    'res_id': sup_ch.id})
                box['sent'].clear()
                inbound(sup_ch, supplier, '+5493580000002', 'Dale, espero')
                Draft.cron_process()
                last = Draft.search([('channel_id', '=', sup_ch.id)], limit=1)
                check("si escribió una persona no arma borrador",
                      last.state == 'handled' and newer.state == 'handled' and not box['sent'],
                      f"{last.state} / {newer.state} / {box['sent']}")

                # 8) Mensaje que no pide respuesta → no se molesta a Sergio.
                box['responder'] = False
                box['sent'].clear()
                inbound(oth_ch, other, '+5493580000003', 'Gracias!')
                Draft.cron_process()
                last = Draft.search([('channel_id', '=', oth_ch.id)], limit=1)
                check("un gracias no genera consulta",
                      last.state == 'no_reply' and not box['sent'], f"{last.state} {box['sent']}")

                # 8b) Sergio contesta desde el celular → queda en el chat, no se reenvía, y
                # lo que esperaba su OK se da por atendido; lo que siga no arma borrador.
                box['responder'] = True
                inbound(oth_ch, other, '+5493580000003', '¿Cuándo pasan a retirar?')
                Draft.cron_process()
                waiting = Draft.search([('channel_id', '=', oth_ch.id), ('state', '=', 'pending')])
                box['sent'].clear()
                echo = account._cristal_post_echo(oth_ch, 'wamid.AUTOTEST1', 'Pasamos el lunes')
                again = account._cristal_post_echo(oth_ch, 'wamid.AUTOTEST1', 'Pasamos el lunes')
                check("lo que Sergio manda desde el celular queda en el chat sin reenviarse",
                      len(echo) == 1 and echo.state == 'sent' and echo.message_type == 'outbound'
                      and not again and not box['sent'],
                      f"{echo.mapped('state')} / repetido {len(again)} / {box['sent']}")
                check("si contestó desde el celular, el borrador se da por atendido",
                      len(waiting) == 1 and waiting.state == 'handled', waiting.mapped('state'))
                inbound(oth_ch, other, '+5493580000003', 'Perfecto, los espero')
                Draft.cron_process()
                last = Draft.search([('channel_id', '=', oth_ch.id)], limit=1)
                check("después de contestar desde el celular no arma borrador",
                      last.state == 'handled' and not box['sent'], f"{last.state} {box['sent']}")
                check("contestar desde el celular en Compras no toca al agente de ventas",
                      not env['cristal.agent.memory'].search([('partner_id', '=', other.id)]),
                      "se creó una memoria de ventas")

                # 8c) v1.82.6 — Un contacto que solo PARTICIPA en un chat de Compras (Sergio
                # está en todos) no tiene ahí "su" chat: los seguimientos a clientes no
                # salen nunca por Compras ni a un número que no es el del cliente.
                from ..services import helpers as hp, tools as _tools  # noqa: F401
                from ..services.tool_registry import ToolRegistry
                if owner.partner_id not in sup_ch.channel_partner_ids:
                    env['discuss.channel.member'].create({
                        'channel_id': sup_ch.id, 'partner_id': owner.partner_id.id})
                found = hp.customer_wa_channel(env, owner.partner_id)
                check("participar en un chat de Compras no lo vuelve el chat del contacto",
                      owner.partner_id in sup_ch.channel_partner_ids
                      and found not in (sup_ch | oth_ch | own_ch)
                      and found.wa_account_id != account,
                      f"devolvió el chat {found.id} de la cuenta {found.wa_account_id.name}")
                check("la cuenta de Compras no es cuenta de ventas",
                      account not in hp.sales_wa_accounts(env)
                      and account.id in hp.nonclient_wa_account_ids(env), "figura como de ventas")
                send_tool = ToolRegistry.get('send_whatsapp')
                blocked = send_tool.execute(
                    env=env, run=None, channel_id=sup_ch.id, body='Seguimiento de prueba',
                    wa_account_id=account.id, mobile_number='+5493580000002') or {}
                check("un mensaje a clientes no sale por la cuenta de Compras",
                      blocked.get('not_sent') and blocked.get('error') == 'CUENTA_NO_ES_DE_CLIENTES',
                      str(blocked)[:200])
                sales = hp.sales_wa_accounts(env)[:1]
                if sales:
                    client = env['res.partner'].create({
                        'name': 'Cliente Autotest', 'mobile': '+5493580000004'})
                    cli_ch = env['discuss.channel'].create({
                        'name': client.name, 'channel_type': 'whatsapp',
                        'whatsapp_number': '5493580000004',
                        'whatsapp_partner_id': client.id, 'wa_account_id': sales.id})
                    env['discuss.channel.member'].create({
                        'channel_id': cli_ch.id, 'partner_id': owner.partner_id.id})
                    check("el chat del cliente es el de su número, en una cuenta de ventas",
                          hp.customer_wa_channel(env, client) == cli_ch
                          and hp.customer_wa_channel(env, owner.partner_id) != cli_ch,
                          "no encontró el chat del cliente o lo tomó como del participante")
                    wrong = send_tool.execute(
                        env=env, run=None, channel_id=cli_ch.id, body='Seguimiento de prueba',
                        wa_account_id=sales.id, mobile_number='+5493580000002') or {}
                    check("no se manda a un número que no es el del chat",
                          wrong.get('not_sent') and wrong.get('error') == 'NUMERO_NO_ES_DEL_CHAT',
                          str(wrong)[:200])

                # 9) Apagado → la cuenta de Compras queda como hoy (nadie la toca).
                config.purchase_consult_enabled = False
                before = Draft.search_count([])
                inbound(oth_ch, other, '+5493580000003', '¿Hay alguien?')
                check("apagado no registra nada",
                      Draft.search_count([]) == before
                      and env['cristal.agent.run'].search_count([]) == runs_before, "registró algo")
                raise _SelftestRollback()
        except _SelftestRollback:
            pass
        except Exception as e:  # noqa: BLE001
            _logger.exception("Autotest Compras")
            results.append(("el autotest corrió entero", False, str(e)[:300]))
        return results


class _SelftestRollback(Exception):
    pass
