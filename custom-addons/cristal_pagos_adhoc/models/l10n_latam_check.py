from odoo import fields, models


class L10nLatamCheck(models.Model):
    _inherit = "l10n_latam.check"

    def _get_last_operation(self):
        """Los cheques de terceros quedaban sin "diario actual".

        l10n_latam_check_ux ordena las operaciones del cheque por la fecha de operación y
        descarta las que no la tienen. Esa fecha se completa al validar desde borrador, así
        que no la tienen los cobros anteriores a instalar ADHOC (30/10/2026) ni los que se
        validan por otro camino (recibos RE-X 0001-00000018 a 20, cheques 484 a 486,
        02/11/2026): el cheque quedaba sin última operación y, con eso, sin diario. Sin
        diario falla la transferencia, el depósito o la entrega del cheque. Cuando falta la
        fecha de operación se usa la de creación del pago.
        """
        self.ensure_one()
        return (
            (self.payment_id + self.operation_ids)
            .filtered(lambda x: x.state not in ["draft", "canceled"])
            .sorted(
                key=lambda payment: (
                    payment.l10n_latam_move_check_ids_operation_date or payment.create_date or fields.Datetime.now(),
                    payment._origin.id,
                )
            )[-1:]
        )
