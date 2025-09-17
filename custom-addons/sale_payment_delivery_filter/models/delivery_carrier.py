from odoo import api, fields, models

class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    # Activa el filtro por medios de pago para este carrier
    restrict_payment_providers = fields.Boolean(
        string="Restringir métodos de pago",
        help="Si está activo, en la tienda solo se mostrarán los métodos de pago "
             "seleccionados para este método de entrega."
    )

    # Métodos de pago permitidos cuando el flag está activo
    payment_provider_ids = fields.Many2many(
        'payment.provider',
        'carrier_payment_provider_rel',
        'carrier_id', 'provider_id',
        string="Métodos de pago permitidos",
        help="Se ofrecerán únicamente estos proveedores cuando el cliente elija "
             "este método de entrega (si ‘Restringir métodos de pago’ está activo)."
    )

    # Helper usado desde payment.provider para validar rápido
    def _is_provider_allowed(self, provider):
        self.ensure_one()
        if not self.restrict_payment_providers:
            return True
        return provider in self.payment_provider_ids
