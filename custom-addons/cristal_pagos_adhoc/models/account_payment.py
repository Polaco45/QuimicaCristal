from odoo import models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    def _get_to_pay_move_lines_domain(self):
        """"Registrar pago" desde una factura imputa a ESA factura.

        account_payment_pro carga en ``to_pay_move_line_ids`` toda la deuda abierta del
        cliente y al validar imputa por orden de vencimiento (FIFO), así que un cobro
        registrado desde la factura FA-A 3539 terminaba pagando la FA-A 3529 y la 3539
        quedaba "no pagada". Cuando el pago nace desde facturas concretas (el asistente
        "Registrar pago" llega con ``active_model='account.move'``), limitamos la deuda a
        esas facturas, que es lo que siempre hizo Odoo y lo que esperan la cobranza
        automática y las reglas de Claudio. Un recibo cargado a mano desde Contabilidad
        sigue trayendo toda la deuda, como lo diseñó ADHOC.
        """
        domain = super()._get_to_pay_move_lines_domain()
        ctx = self.env.context
        if ctx.get("active_model") == "account.move" and ctx.get("active_ids"):
            domain.append(("move_id", "in", list(ctx["active_ids"])))
        return domain

    def action_post(self):
        """Los cheques de terceros nuevos quedaban sin "diario actual".

        Con account_payment_pro, los cobros validados desde el asistente de pago (recibos
        RE-X 0001-00000018 a 20, cheques 484 a 486, 02/11/2026) quedaron con el pago en el
        diario 35 y validado, pero el cheque sin current_journal_id: el cómputo guardado
        no se volvió a ejecutar. Sin diario puede fallar la transferencia, el depósito o
        la venta del cheque. Al validar, se recalcula el diario de los cheques del pago.
        """
        res = super().action_post()
        self._cristal_recompute_check_journal()
        return res

    def _cristal_recompute_check_journal(self):
        Check = self.env["l10n_latam.check"]
        checks = Check.browse()
        for name in ("l10n_latam_new_check_ids", "l10n_latam_move_check_ids"):
            if name in self._fields:
                checks |= self.mapped(name)
        if checks:
            self.env.add_to_compute(Check._fields["current_journal_id"], checks)
            checks.flush_recordset(["current_journal_id"])
