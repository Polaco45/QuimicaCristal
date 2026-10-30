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
