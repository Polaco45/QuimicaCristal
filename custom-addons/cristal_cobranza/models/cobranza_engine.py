# -*- coding: utf-8 -*-
"""
Motor de cobranza. Vive sobre cristal.agent.run para reusar el dashboard de
auditoría del agente y ser invocable desde un ir.cron con `model.cron_cobranza()`
(mismo patrón que las cadencias comerciales).

Flujo del cron (diario):
  1. Junta los clientes con facturas vencidas.
  2. Para cada uno calcula el snapshot (vencidas / por vencer / días de mora).
  3. Decide el nivel: 0/5/10/15/20, escalando de a UN paso por vez.
  4. Ejecuta: WhatsApp (0/5/10) o actividad de llamada/visita (15/20).
  5. Registra la acción y avanza el estado del cliente (anti-spam).

El cron nace DESACTIVADO y arranca en modo prueba (un solo cliente).
"""
import base64
import logging
import re

from odoo import models, fields, api

from .res_partner import COBRANZA_STAGES

_logger = logging.getLogger(__name__)

REPORT_FULL = 'cristal_cobranza.action_report_estado_cuenta_full'
REPORT_LIGHT = 'cristal_cobranza.action_report_estado_cuenta'


class CristalAgentRun(models.Model):
    _inherit = 'cristal.agent.run'

    trigger = fields.Selection(
        selection_add=[('cron_cobranza', 'Cron cobranza')],
        ondelete={'cron_cobranza': 'set default'},
    )

    # ────────────────────── Entrada del cron ──────────────────────
    @api.model
    def cron_cobranza(self):
        """Punto de entrada llamado por el ir.cron."""
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config or not config.cobranza_enabled:
            _logger.info("💤 Cobranza desactivada (cobranza_enabled=False). Nada que hacer.")
            return

        try:
            run = self.sudo().create({
                'trigger': 'cron_cobranza',
                'state': 'running',
            })
        except Exception as e:  # noqa: BLE001 — el run es solo auditoría
            _logger.warning("No se pudo crear el run de cobranza (sigo igual): %s", e)
            run = self.browse()

        partners = self._cobranza_candidate_partners(config)
        _logger.info("💰 Cobranza: %s clientes candidatos con vencido.", len(partners))

        resumen = {'whatsapp': 0, 'activity': 0, 'skipped': 0, 'reset': 0, 'error': 0}
        for partner in partners:
            try:
                outcome = self._cobranza_process_partner(partner, config, run)
                resumen[outcome] = resumen.get(outcome, 0) + 1
            except Exception as e:  # noqa: BLE001 — un cliente no debe tumbar el cron
                resumen['error'] += 1
                _logger.exception("Error en cobranza de %s: %s", partner.display_name, e)

        summary = (
            "Cobranza ejecutada. WhatsApp: {whatsapp} · Actividades: {activity} · "
            "Salteados: {skipped} · Reseteados: {reset} · Errores: {error}"
        ).format(**resumen)
        run.sudo().write({'state': 'done', 'final_response': summary})
        _logger.info("✅ %s", summary)
        return resumen

    def _cobranza_candidate_partners(self, config):
        """Entidades comerciales con al menos una factura de venta vencida."""
        today = fields.Date.context_today(self)
        moves = self.env['account.move'].sudo().search([
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('amount_residual', '>', 0),
            ('invoice_date_due', '<', today),
        ])
        partners = moves.mapped('commercial_partner_id').filtered(
            lambda p: not p.cobranza_exclude)

        if config.cobranza_test_mode:
            test = config.cobranza_test_partner_id
            partners = partners.filtered(lambda p: test and p.id == test.id)
        return partners

    # ────────────────────── Procesamiento por cliente ──────────────────────
    def _cobranza_process_partner(self, partner, config, run):
        snap = partner.cobranza_snapshot(
            ventana_dias=config.cobranza_ventana_dias or 5)

        # Sin vencido: si venía en cadencia, reseteamos para el próximo ciclo.
        if snap['total_vencido'] <= 0:
            if partner.cobranza_last_stage:
                partner.sudo().write({
                    'cobranza_last_stage': False,
                    'cobranza_last_action_date': False,
                })
                return 'reset'
            return 'skipped'

        stage = self._cobranza_decide_stage(partner, snap, config)
        if stage is None:
            return 'skipped'

        if stage in (0, 5, 10):
            # Doble canal: WhatsApp + Email, cada uno con el PDF adjunto. Son
            # independientes (el email no depende de la aprobación de Meta).
            ok_wa = self._cobranza_do_whatsapp(partner, stage, snap, config, run)
            ok_mail = self._cobranza_do_email(partner, stage, snap, config, run)
            outcome = 'whatsapp' if (ok_wa or ok_mail) else 'error'
        else:
            self._cobranza_do_activity(partner, stage, snap, config, run)
            outcome = 'activity'

        # Avanzar estado del cliente (anti-spam) solo si se ejecutó algo.
        if outcome in ('whatsapp', 'activity'):
            partner.sudo().write({
                'cobranza_last_stage': str(stage),
                'cobranza_last_action_date': snap['today'],
            })
        return outcome

    def _cobranza_decide_stage(self, partner, snap, config):
        """Devuelve el nivel a ejecutar (int) o None."""
        total = snap['total_vencido']
        if total < (config.cobranza_min_amount or 0.0):
            return None
        dias = snap['dias_mora_max']
        today = snap['today']
        last = int(partner.cobranza_last_stage) if partner.cobranza_last_stage else None

        # Nunca contactado: arranca en el día 0 (entrega comprobantes + estado).
        if last is None:
            return 0

        # Ya en el último paso: no escala más.
        if last >= COBRANZA_STAGES[-1]:
            return None

        nxt = COBRANZA_STAGES[COBRANZA_STAGES.index(last) + 1]
        gap_ok = True
        if partner.cobranza_last_action_date:
            gap = (today - partner.cobranza_last_action_date).days
            gap_ok = gap >= (config.cobranza_min_gap_days or 0)
        if dias >= nxt and gap_ok:
            return nxt
        return None

    # ────────────────────── Ejecución: WhatsApp ──────────────────────
    def _cobranza_do_whatsapp(self, partner, stage, snap, config, run):
        template = {
            0: config.cobranza_template_day0_id,
            5: config.cobranza_template_day5_id,
            10: config.cobranza_template_day10_id,
        }.get(stage)
        if not template:
            # Fallback: buscar por el nombre técnico que crea el post_init_hook.
            tname = {
                0: 'cobranza_dia_0_recordatorio',
                5: 'cobranza_dia_5_seguimiento',
                10: 'cobranza_dia_10_ultimatum',
            }.get(stage)
            template = self.env['whatsapp.template'].sudo().search(
                [('template_name', '=', tname)], limit=1)

        if not template:
            self._cobranza_log(partner, stage, 'whatsapp', snap, run,
                               state='skipped',
                               note="No hay template configurado para este nivel.")
            _logger.warning("⚠️ Sin template para día %s (partner %s).", stage, partner.display_name)
            return False
        if template.status != 'approved':
            self._cobranza_log(partner, stage, 'whatsapp', snap, run,
                               state='skipped',
                               note="Template '%s' no aprobado por Meta (status=%s)."
                                    % (template.name, template.status))
            _logger.warning("⚠️ Template día %s no aprobado (%s).", stage, template.status)
            return False

        # PDF para archivo/chatter (el que viaja por WA lo genera el composer
        # desde template.report_id; este es la copia auditable).
        report_ref = REPORT_FULL if stage == 0 else REPORT_LIGHT
        attachment = self._cobranza_generate_pdf(partner, report_ref, stage)

        importe = partner.cobranza_format_amount(snap['total_vencido'])
        # El mensaje va al contacto de facturación; el estado de cuenta se
        # consolida sobre la entidad comercial (partner). Las variables {{1}}/{{2}}
        # son de tipo Campo → el composer las autocompleta desde el registro; no
        # las pasamos a mano.
        recipient = partner._cobranza_billing_contact()
        result = self._cobranza_composer_send(partner, recipient, template)

        if result.get('error'):
            self._cobranza_log(partner, stage, 'whatsapp', snap, run,
                               state='failed', attachment=attachment,
                               note=result['error'])
            return False

        wa_msg = result.get('wa_message')
        self._cobranza_log(partner, stage, 'whatsapp', snap, run,
                           state='sent', attachment=attachment, wa_message=wa_msg,
                           note="Enviado template '%s' a %s con importe %s."
                                % (template.name, recipient.name, importe))
        # Dejar rastro en el chatter del cliente.
        try:
            body = ("💰 Cobranza día %s enviada por WhatsApp — vencido %s (%s facturas)."
                    % (stage, importe, snap['cant_vencidas']))
            partner.message_post(body=body,
                                 attachment_ids=attachment.ids if attachment else False)
        except Exception:  # noqa: BLE001
            pass
        return True

    # ────────────────────── Ejecución: Email ──────────────────────
    def _cobranza_do_email(self, partner, stage, snap, config, run):
        """Manda el mismo estado de cuenta por email al contacto de facturación.
        Es independiente de WhatsApp: no depende de la aprobación de Meta."""
        recipient = partner._cobranza_billing_contact()
        email = (recipient.email or partner.email or '').strip()
        if not email:
            self._cobranza_log(partner, stage, 'email', snap, run, state='skipped',
                               note="Sin email de facturación.")
            return False

        template = self._cobranza_email_template(stage)
        if not template:
            self._cobranza_log(partner, stage, 'email', snap, run, state='skipped',
                               note="No hay plantilla de email para el día %s." % stage)
            return False

        report_ref = REPORT_FULL if stage == 0 else REPORT_LIGHT
        attachment = self._cobranza_generate_pdf(partner, report_ref, stage)
        try:
            template.sudo().send_mail(
                partner.id, force_send=True,
                email_values={
                    'email_to': email,
                    'attachment_ids': [(4, attachment.id)] if attachment else False,
                })
        except Exception as e:  # noqa: BLE001
            self._cobranza_log(partner, stage, 'email', snap, run, state='failed',
                               attachment=attachment, note="Error email: %s" % e)
            _logger.exception("Error enviando email de cobranza: %s", e)
            return False

        importe = partner.cobranza_format_amount(snap['total_vencido'])
        self._cobranza_log(partner, stage, 'email', snap, run, state='sent',
                           attachment=attachment,
                           note="Email día %s a %s (vencido %s)." % (stage, email, importe))
        try:
            partner.message_post(
                body="📧 Cobranza día %s enviada por email a %s." % (stage, email))
        except Exception:  # noqa: BLE001
            pass
        return True

    def _cobranza_email_template(self, stage):
        """Devuelve la mail.template del día indicado (o False)."""
        xmlid = {
            0: 'cristal_cobranza.mail_template_cobranza_day0',
            5: 'cristal_cobranza.mail_template_cobranza_day5',
            10: 'cristal_cobranza.mail_template_cobranza_day10',
        }.get(stage)
        if not xmlid:
            return False
        return self.env.ref(xmlid, raise_if_not_found=False)

    def _cobranza_composer_send(self, doc_partner, recipient, template):
        """Envía un template aprobado vía whatsapp.composer (mismo mecanismo que
        usa Claudio para mandar fuera de la ventana de 24hs).

        Las variables del template son de tipo Campo, así que el composer las
        autocompleta solo desde el registro de doc_partner.

        doc_partner: entidad comercial (sobre la que se renderiza el estado de
                     cuenta que viaja como documento del template).
        recipient:   contacto al que se le manda (su celular).
        """
        env = self.env
        mobile = self._cobranza_normalize_mobile(
            recipient.mobile or recipient.phone
            or doc_partner.mobile or doc_partner.phone or '')
        if not mobile:
            return {'error': "Ni %s ni %s tienen celular válido."
                    % (recipient.display_name, doc_partner.display_name)}

        model = template.model_id.model if template.model_id else 'res.partner'
        if model != 'res.partner':
            return {'error': "El template de cobranza debe estar sobre res.partner (está sobre %s)." % model}

        try:
            Composer = env['whatsapp.composer'].sudo()
            composer = Composer.with_context(
                active_model='res.partner',
                active_ids=[doc_partner.id],
                default_res_model='res.partner',
                default_res_ids=str(doc_partner.id),
            ).create({
                'res_model': 'res.partner',
                'res_ids': str(doc_partner.id),
                'wa_template_id': template.id,
                'phone': mobile,
            })
            send_method = None
            for name in ('action_send_whatsapp_template', '_send_whatsapp_template'):
                if hasattr(composer, name):
                    send_method = getattr(composer, name)
                    break
            if not send_method:
                return {'error': "No encontré método de envío en whatsapp.composer."}
            send_method()
        except Exception as e:  # noqa: BLE001
            _logger.exception("Error enviando template de cobranza: %s", e)
            return {'error': "No se pudo enviar el template: %s" % e}

        wa_msg = env['whatsapp.message'].sudo().search([
            ('wa_template_id', '=', template.id),
            ('mobile_number', 'ilike', mobile[-8:]),
        ], order='create_date desc', limit=1)
        return {'ok': True, 'wa_message': wa_msg or False}

    # ────────────────────── Ejecución: Actividad ──────────────────────
    def _cobranza_do_activity(self, partner, stage, snap, config, run):
        env = self.env
        importe = partner.cobranza_format_amount(snap['total_vencido'])
        oldest = snap['oldest_due'] and snap['oldest_due'].strftime('%d/%m/%Y') or '—'

        if stage == 15:
            type_names = ['Llamada', 'Phone Call', 'Call']
            user = config.cobranza_call_user_id or config.owner_user_id
            summary = "Llamar por cobranza — %s vencido" % importe
        else:  # 20
            type_names = ['Reunión', 'Meeting', 'Visita', 'To Do']
            user = config.cobranza_visit_user_id or config.owner_user_id
            summary = "Visita de cobranza — %s vencido" % importe

        atype = env['mail.activity.type'].sudo().search(
            [('name', 'in', type_names)], limit=1) or \
            env['mail.activity.type'].sudo().search([], limit=1)

        note = (
            "Gestión de cobranza (día %s).<br/>"
            "Total vencido: <b>%s</b> — %s factura(s), la más antigua vence el %s "
            "(%s días de mora).<br/>Zona: %s."
        ) % (stage, importe, snap['cant_vencidas'], oldest,
             snap['dias_mora_max'], dict(partner._fields['agent_zone'].selection).get(
                 partner.agent_zone, partner.agent_zone or '—'))

        activity = env['mail.activity'].sudo().create({
            'res_model_id': env['ir.model']._get_id('res.partner'),
            'res_model': 'res.partner',
            'res_id': partner.id,
            'activity_type_id': atype.id if atype else False,
            'summary': summary,
            'note': note,
            'date_deadline': snap['today'],
            'user_id': user.id if user else self.env.uid,
        })
        self._cobranza_log(partner, stage, 'activity', snap, run,
                           state='sent', activity=activity, note=summary)
        return activity

    # ────────────────────── Helpers ──────────────────────
    def _cobranza_generate_pdf(self, partner, report_ref, stage):
        try:
            report = self.env.ref(report_ref)
            pdf_content, _ctype = report.sudo()._render_qweb_pdf(report_ref, [partner.id])
        except Exception as e:  # noqa: BLE001
            _logger.exception("No se pudo generar el PDF de estado de cuenta: %s", e)
            return self.env['ir.attachment']
        filename = "EstadoCuenta_%s.pdf" % (re.sub(r'\W+', '_', partner.name or 'cliente'))
        return self.env['ir.attachment'].sudo().create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': 'res.partner',
            'res_id': partner.id,
            'mimetype': 'application/pdf',
        })

    def _cobranza_log(self, partner, stage, channel, snap, run, state='sent',
                      attachment=None, wa_message=None, activity=None, note=None):
        return self.env['cristal.cobranza.action'].sudo().create({
            'partner_id': partner.id,
            'stage': str(stage),
            'channel': channel,
            'state': state,
            'total_vencido': snap['total_vencido'],
            'amount_display': partner.cobranza_format_amount(snap['total_vencido']),
            'cant_vencidas': snap['cant_vencidas'],
            'dias_mora_max': snap['dias_mora_max'],
            'attachment_id': attachment.id if attachment else False,
            'wa_message_id': wa_message.id if wa_message else False,
            'activity_id': activity.id if activity else False,
            'run_id': run.id if run else False,
            'note': note,
        })

    @staticmethod
    def _cobranza_normalize_mobile(raw):
        if not raw:
            return ''
        cleaned = re.sub(r'[^\d+]', '', raw)
        if not cleaned:
            return ''
        if not cleaned.startswith('+'):
            if cleaned.startswith('54'):
                cleaned = '+' + cleaned
            else:
                cleaned = '+54' + cleaned.lstrip('0')
        return cleaned

    @staticmethod
    def _cobranza_sanitize(val):
        if val is None:
            return ''
        s = str(val)
        s = re.sub(r'[\r\n]+', ' ', s)
        s = s.replace('\t', ' ')
        s = re.sub(r'[\x00-\x1F\x7F]', '', s)
        s = re.sub(r' +', ' ', s).strip()
        return s[:1020]
