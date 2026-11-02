# -*- coding: utf-8 -*-
"""
v1.51 — Modo administración, etapa 2: e-cheqs recibidos.

Sergio (02/11/2026): "los e-cheqs recibidos se aceptan, se asienta el cobro y se valida,
y sale un mail desde admin@ pidiendo el comprobante de pago y el certificado de
retención y avisando que de ahora en más manden todo a admin@quimicacristal.com.ar.
Todas las comunicaciones son internas dentro de Odoo."

Aceptar el e-cheq en el Galicia necesita la sesión del banco, así que lo hace Claudio
cuando Sergio abre el banco y después llama por RPC a
``cristal.agent.admin.register_echeq``, que:

1. Registra el cobro como los recibos RE-X 0001-00000018 a 20 (02/11): diario 35,
   "Nuevo Cheque de Tercero", imputado a las facturas del cliente (las que se pasan o,
   si no, las más viejas hasta cubrir el importe) y validado. Si el cheque es menor,
   la diferencia queda abierta como retención.
2. Manda el mail al cliente desde admin@ en el chatter del recibo, con el texto del doc
   de Sergio. Si admin@ todavía no recibe (falta la redirección de DonWeb), no sale: queda
   como nota en el recibo y se avisa en el canal de administración.
3. Lo que falla le llega a Sergio en el canal "Administración · Agente" de Odoo.
"""
import logging
from datetime import date

from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)

ECHEQ_JOURNAL_ID = 35            # Cheques de terceros electrónicos
ADMIN_EMAIL = 'admin@quimicacristal.com.ar'
ADMIN_CHANNEL_NAME = 'Administración · Agente'
SERGIO_PARTNER_ID = 3
PARAM_MAIL_READY = 'cristal_agent.admin_mail_ready'


def _money(amount):
    """$ 1.421.990,26"""
    txt = f"{amount:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"${txt}"


class CristalAgentAdmin(models.AbstractModel):
    _name = 'cristal.agent.admin'
    _description = 'Cristal Agent — modo administración'

    # ── E-cheqs recibidos ──────────────────────────────────────────────────

    @api.model
    def register_echeq(self, partner_id, check_number, amount, payment_date,
                       invoice_ids=None, bank_id=None, issuer_vat=None, send_mail=True):
        """Registra y valida el cobro de un e-cheq recibido y avisa al cliente.

        Devuelve un dict con ``ok``, ``payment_id``, ``receipt``, ``difference``,
        ``mail_sent`` y ``summary`` (o ``error``). Es idempotente: si el cheque ya
        está registrado devuelve ese cobro sin tocar nada.
        """
        if not (self.env.su or self.env.user.has_group('account.group_account_invoice')):
            raise AccessError("Registrar e-cheqs requiere permisos de facturación.")
        try:
            amount = round(float(amount or 0), 2)
            check_number = str(check_number or '').strip()
            partner = self.env['res.partner'].browse(int(partner_id or 0)).exists()
            if not partner or not check_number or amount <= 0 or not payment_date:
                return {'ok': False, 'error': "Faltan datos: cliente, número, importe y fecha de pago."}
            partner = partner.commercial_partner_id
            payment_date = fields.Date.to_date(payment_date)

            dup = self._find_registered_check(partner, check_number, issuer_vat)
            if dup:
                pay = dup.payment_id
                return {'ok': True, 'duplicate': True, 'payment_id': pay.id, 'receipt': pay.name,
                        'summary': f"El e-cheq {check_number} ya estaba registrado en {pay.name}."}

            journal = self.env['account.journal'].browse(ECHEQ_JOURNAL_ID).exists()
            method_line = journal.inbound_payment_method_line_ids.filtered(
                lambda l: l.code == 'new_third_party_checks')[:1]
            if not method_line:
                return self._fail(f"El diario {ECHEQ_JOURNAL_ID} no tiene el método «Nuevo Cheque de Tercero».",
                                  partner)

            invoices, is_retention = self._echeq_invoices(partner, amount, invoice_ids)
            due_before = sum(invoices.mapped('amount_residual'))
            receivable = invoices.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled)

            check_vals = {'name': check_number, 'payment_date': payment_date, 'amount': amount}
            if bank_id:
                check_vals['bank_id'] = int(bank_id)
            if issuer_vat:
                check_vals['issuer_vat'] = str(issuer_vat)
            ref = f"E-cheq {check_number}"
            if invoices:
                ref += " · " + ", ".join(invoices.mapped('name'))
            vals = {
                'partner_id': partner.id,
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'journal_id': journal.id,
                'payment_method_line_id': method_line.id,
                'amount': amount,
                'date': fields.Date.context_today(self),
                'memo': ref,
                'l10n_latam_new_check_ids': [Command.create(check_vals)],
            }
            Payment = self.env["account.payment"]
            with self.env.cr.savepoint():
                payment = Payment.create(vals)
                if receivable and "to_pay_move_line_ids" in Payment._fields:
                    payment.to_pay_move_line_ids = [Command.set(receivable.ids)]
                payment.action_post()
        except Exception as e:
            _logger.exception("register_echeq falló")
            return self._fail(f"No pude registrar el e-cheq {check_number} de {_money(float(amount or 0))}: {e}",
                              None)

        open_left = max(round(due_before - amount, 2), 0.0) if invoices else 0.0
        difference = open_left if is_retention else 0.0
        if open_left and not is_retention:
            self.notify_admin(
                f"E-cheq {check_number} de {partner.name} imputado a las facturas más viejas "
                f"({', '.join(invoices.mapped('name'))}); quedan {_money(open_left)} sin cubrir "
                "que no parecen retención. Revisalo.", record=payment)
        mail_sent, mail_note = (False, "no pedido")
        if send_mail:
            mail_sent, mail_note = self._send_echeq_mail(
                payment, check_number, amount, payment_date, invoices, difference)
        summary = (f"E-cheq {check_number} de {partner.name} por {_money(amount)} registrado y "
                   f"validado en {payment.name}"
                   + (f"; quedan {_money(difference)} abiertos como retención" if difference else "")
                   + f". Mail: {mail_note}.")
        return {'ok': True, 'payment_id': payment.id, 'receipt': payment.name,
                'invoices': invoices.mapped('name'), 'difference': difference,
                'mail_sent': mail_sent, 'summary': summary}

    def _find_registered_check(self, partner, number, issuer_vat=None):
        domain = [('name', '=', number),
                  ('payment_id.state', 'not in', ['draft', 'canceled'])]
        if issuer_vat:
            domain.append(('issuer_vat', '=', str(issuer_vat)))
        else:
            domain.append(('payment_id.partner_id', 'child_of', partner.id))
        return self.env['l10n_latam.check'].search(domain, limit=1)

    def _echeq_invoices(self, partner, amount, invoice_ids=None):
        """Facturas a las que va el cheque y si la diferencia es una retención.

        Devuelve ``(facturas, es_retencion)``. Con ``invoice_ids`` son esas y la diferencia
        es retención. Si no, en este orden: una factura del mismo importe; las más viejas que
        suman justo el importe; una sola factura apenas mayor (hasta 10 %: retención); y si
        nada de eso, las más viejas hasta cubrir el importe, SIN pedir certificado (la última
        queda con saldo porque el cheque no alcanza, no por una retención).
        """
        Move = self.env['account.move']
        base = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                ('payment_state', 'in', ['not_paid', 'partial']),
                ('commercial_partner_id', '=', partner.id)]
        if invoice_ids:
            invoices = Move.search(base + [('id', 'in', [int(i) for i in invoice_ids])])
            if len(invoices) != len(set(invoice_ids)):
                raise UserError("Alguna de las facturas no es del cliente o ya está pagada.")
            return invoices, True
        open_invoices = Move.search(base, order='invoice_date asc, id asc')
        same = open_invoices.filtered(lambda i: abs(i.amount_residual - amount) <= 1)
        if same:
            return same[:1], False
        picked = Move.browse()
        covered = 0.0
        for inv in open_invoices:
            picked |= inv
            covered += inv.amount_residual
            if abs(covered - amount) <= 1:
                return picked, False
            if covered > amount:
                break
        near = open_invoices.filtered(
            lambda i: i.amount_residual > amount and i.amount_residual - amount <= i.amount_residual * 0.10)
        if near:
            return near[:1], True
        picked = Move.browse()
        covered = 0.0
        for inv in open_invoices:
            if covered >= amount - 0.01:
                break
            picked |= inv
            covered += inv.amount_residual
        return picked, False

    def _send_echeq_mail(self, payment, number, amount, payment_date, invoices, difference):
        """Mail al cliente desde admin@ en el chatter del recibo (texto de Sergio, 02/11)."""
        partner = payment.partner_id
        recipients = self._admin_recipients(partner, invoices)
        body = self._echeq_mail_body(payment, number, amount, payment_date, invoices, difference)
        ready = self.env['ir.config_parameter'].sudo().get_param(PARAM_MAIL_READY) in ('1', 'True', 'true')
        if not ready or not recipients:
            why = ("admin@ todavía no recibe en Odoo (falta la redirección de DonWeb)" if not ready
                   else "el cliente no tiene mail cargado")
            payment.message_post(
                body=Markup("<p><b>Mail al cliente pendiente</b> (%s). Texto:</p>") % why + body,
                message_type='comment', subtype_xmlid='mail.mt_note')
            self.notify_admin(f"E-cheq {number} de {partner.name} registrado en {payment.name}, "
                              f"pero el mail no salió: {why}.", record=payment)
            return False, f"no salió ({why})"
        payment.with_context(mail_notify_author=False).message_post(
            body=body,
            subject=f"Recibimos su e-cheq N° {number} · Química Cristal",
            message_type='comment', subtype_xmlid='mail.mt_comment',
            partner_ids=recipients.ids,
            email_from=f'"Química Cristal · Administración" <{ADMIN_EMAIL}>',
            author_id=self.env.ref('base.partner_root').id)
        return True, "enviado a " + ", ".join(recipients.mapped('email'))

    def _admin_recipients(self, partner, invoices):
        contacts = invoices.mapped('partner_id').filtered('email')
        if not contacts:
            contacts = partner.child_ids.filtered(lambda c: c.type == 'invoice' and c.email)
        if not contacts and partner.email:
            contacts = partner
        return contacts

    def _echeq_mail_body(self, payment, number, amount, payment_date, invoices, difference):
        fecha = payment_date.strftime('%d/%m/%Y') if isinstance(payment_date, date) else payment_date
        lines = [
            "Hola, buen día.",
            f"Recibimos el e-cheq N° {html_escape(number)} por {_money(amount)} con fecha de pago "
            f"{fecha} y ya lo registramos en su cuenta (recibo {html_escape(payment.name)}).",
        ]
        if difference:
            facturas = ", ".join(invoices.mapped('name'))
            lines.append(
                f"Les pedimos que nos envíen el comprobante de pago y, por los {_money(difference)} "
                f"de diferencia con la factura {html_escape(facturas)}, el certificado de retención.")
        else:
            lines.append("Les pedimos que nos envíen el comprobante de pago.")
        lines += [
            "De ahora en más, por favor envíen todos los comprobantes, certificados y consultas "
            f"administrativas a {ADMIN_EMAIL}.",
            "Muchas gracias.",
            "Administración · Química Cristal",
        ]
        return Markup("".join(f"<p>{l}</p>" for l in lines))

    # ── Avisos a Sergio (dentro de Odoo) ───────────────────────────────────

    @api.model
    def notify_admin(self, message, record=None):
        """Avisa en el canal "Administración · Agente", mencionando a Sergio."""
        channel = self._admin_channel()
        sergio = self.env['res.partner'].sudo().browse(SERGIO_PARTNER_ID).exists()
        body = ""
        if sergio:
            body += (f'<a href="#" data-oe-id="{sergio.id}" data-oe-model="res.partner" '
                     f'class="o_mail_redirect">@{html_escape(sergio.name.split()[0])}</a> ')
        body += html_escape(message)
        if record:
            body += (f' <a href="/odoo/{record._name}/{record.id}">'
                     f'{html_escape(record.display_name)}</a>')
        channel.sudo().message_post(
            body=Markup(f"<p>{body}</p>"), message_type="comment", subtype_xmlid="mail.mt_comment",
            author_id=self.env.ref('base.partner_root').id,
            partner_ids=sergio.ids)
        return True

    def _admin_channel(self):
        Channel = self.env['discuss.channel'].sudo()
        channel = Channel.search([('name', '=', ADMIN_CHANNEL_NAME), ('channel_type', '=', 'channel')], limit=1)
        if not channel:
            channel = Channel.create({'name': ADMIN_CHANNEL_NAME, 'channel_type': 'channel',
                                      'description': "Avisos del modo administración del Cristal Agent."})
            members = self.env['res.partner'].sudo().browse([SERGIO_PARTNER_ID]).exists()
            config = self.env['cristal.agent.config'].sudo().get_active()
            members |= config.owner_partner_id
            if members:
                channel.add_members(partner_ids=members.ids)
        return channel

    def _fail(self, message, partner):
        try:
            self.notify_admin(message, record=partner)
        except Exception:
            _logger.exception("No pude avisar en el canal de administración")
        return {'ok': False, 'error': message}
