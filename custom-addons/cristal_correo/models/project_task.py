# -*- coding: utf-8 -*-
"""Tareas de las bandejas de correo: ubicación, respuesta automática y remitente."""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """Un mail que no matcheó ningún alias pero vino de una casilla leída por IMAP
        entra a la bandeja de esa casilla (y no a una tarea sin proyecto)."""
        Account = self.env['cristal.mail.account'].sudo()
        custom_values = dict(custom_values or {})
        account = Account.browse()
        server_id = self.env.context.get('default_fetchmail_server_id') \
            or self.env.context.get('fetchmail_server_id')
        if server_id:
            account = Account.search([('fetchmail_server_id', '=', server_id)], limit=1)
        if not account:
            # Por destinatario (To / Cc / Delivered-To que Odoo junta en 'recipients').
            rcpt = ' '.join(str(msg_dict.get(k) or '') for k in ('to', 'cc', 'recipients')).lower()
            for acc in Account.search([('project_id', '!=', False)]):
                if acc.email.strip().lower() in rcpt:
                    account = acc
                    break
        if not custom_values.get('project_id') and account.project_id:
            custom_values['project_id'] = account.project_id.id
        task = super().message_new(msg_dict, custom_values=custom_values)
        account = account or Account._for_project(task.project_id)
        if account and account.auto_reply:
            task._cristal_auto_reply(account, msg_dict)
        return task

    def _cristal_auto_reply(self, account, msg_dict):
        """Acuse de recibo al remitente de un mail NUEVO (las respuestas a un hilo no
        pasan por message_new). Nunca a remitentes automáticos ni propios."""
        self.ensure_one()
        email_from = msg_dict.get('email_from') or self.email_from or ''
        subject = (msg_dict.get('subject') or '').lower()
        if not email_from or account._is_automatic_sender(email_from) \
                or subject.startswith(('respuesta automática', 'auto', 'out of office',
                                       'fuera de la oficina', 'undeliverable')):
            return
        partner = self.partner_id
        if not partner:
            try:
                partner = self._partner_find_from_emails_single([email_from], no_create=False)
            except Exception:
                partner = self.env['res.partner'].sudo().search(
                    [('email', '=ilike', email_from)], limit=1)
        if not partner:
            return
        try:
            self.with_context(cristal_auto_reply=True).message_post(
                body=account.auto_reply_body,
                subject=f"Re: {msg_dict.get('subject') or self.name}",
                message_type='comment', subtype_xmlid='mail.mt_comment',
                partner_ids=[partner.id], email_from=account.email_formatted,
                author_id=self.env.ref('base.partner_root').id)
        except Exception as e:
            _logger.warning("Respuesta automática de %s falló: %s", account.email, e)

    def message_post(self, **kwargs):
        """Lo que se responde desde una tarea de bandeja sale DESDE la casilla
        (ej. admin@quimicacristal.com.ar) y no desde el usuario que contesta."""
        if len(self) == 1 and self.project_id and not kwargs.get('email_from') \
                and kwargs.get('message_type') == 'comment' \
                and kwargs.get('subtype_xmlid', 'mail.mt_comment') == 'mail.mt_comment':
            account = self.env['cristal.mail.account'].sudo()._for_project(self.project_id)
            if account:
                kwargs['email_from'] = account.email_formatted
        return super().message_post(**kwargs)
