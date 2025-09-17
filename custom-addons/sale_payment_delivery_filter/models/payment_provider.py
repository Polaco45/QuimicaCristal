from odoo import api, fields, models

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    # Limitar proveedor por método(s) de entrega
    restrict_delivery_carriers = fields.Boolean(
        string="Restringir por método de entrega",
        help="Si está activo, este proveedor solo se ofrecerá cuando el pedido "
             "use alguno de los métodos de entrega seleccionados."
    )

    delivery_carrier_ids = fields.Many2many(
        'delivery.carrier',
        'provider_delivery_carrier_rel',
        'provider_id', 'carrier_id',
        string="Métodos de entrega permitidos",
        help="Seleccione los métodos de entrega en los que este proveedor estará disponible "
             "cuando ‘Restringir por método de entrega’ esté activo."
    )

    # ----------------------------
    # Utilidades / Filtrado
    # ----------------------------
    def _get_sale_order_from_context(self):
        """Intenta obtener el sale.order actual desde el contexto/website."""
        ctx = self.env.context
        order = ctx.get('sale_order')
        if isinstance(order, int):
            order = self.env['sale.order'].browse(order)

        if not order:
            so_id = ctx.get('sale_order_id') or ctx.get('website_sale_current_order')
            if so_id:
                order = self.env['sale.order'].browse(so_id)

        if not order and 'website' in self.env:
            # Soporta get_current_website y _get_current_website según versión
            try:
                Website = self.env['website'].sudo()
                getter = getattr(Website, 'get_current_website', None) or getattr(Website, '_get_current_website', None)
                website = getter() if getter else None
                if website:
                    order = website.sale_get_order()
            except Exception:
                order = None

        return order

    def _filter_by_delivery_on_order(self, order):
        """Filtra self por carrier del pedido aplicando ambas reglas:

        1) Si el proveedor tiene 'restrict_delivery_carriers' activo, solo queda
           si el carrier del pedido está en delivery_carrier_ids.
        2) Si el carrier del pedido tiene 'restrict_payment_providers' activo,
           el proveedor debe estar en carrier.payment_provider_ids.
        """
        if not order or not order.carrier_id:
            return self

        carrier = order.carrier_id

        providers = self.filtered(
            lambda p: (not p.restrict_delivery_carriers) or (carrier in p.delivery_carrier_ids)
        )
        if carrier.restrict_payment_providers:
            providers = providers.filtered(lambda p: p in carrier.payment_provider_ids)

        return providers

    # Punto central usado por portal/website para listar proveedores compatibles
    @api.model
    def _get_compatible_providers(self, *args, **kwargs):
        providers = super()._get_compatible_providers(*args, **kwargs)
        order = providers._get_sale_order_from_context()
        if order:
            return providers._filter_by_delivery_on_order(order)
        return providers
