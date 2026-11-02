from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    receiver_name = fields.Char(
        string="Recibido por",
        help="Nombre y aclaración de la persona que recibió la entrega. "
        "Se completa al firmar y se imprime en el remito de entrega.",
        copy=False,
        tracking=True,
    )

    # Datos del cliente a la vista para el repartidor, sin tener que abrir la
    # ficha del contacto.
    partner_delivery_address = fields.Char(
        string="Dirección de entrega",
        compute="_compute_partner_delivery_address",
    )
    partner_phone = fields.Char(
        string="Teléfono",
        related="partner_id.phone",
        readonly=True,
    )
    partner_mobile = fields.Char(
        string="Celular",
        related="partner_id.mobile",
        readonly=True,
    )

    @api.depends(
        "partner_id", "partner_id.street", "partner_id.street2",
        "partner_id.city", "partner_id.zip", "partner_id.state_id",
    )
    def _compute_partner_delivery_address(self):
        for picking in self:
            partner = picking.partner_id.sudo()
            if not partner:
                picking.partner_delivery_address = False
                continue
            address = partner._display_address(without_company=True) or ""
            picking.partner_delivery_address = ", ".join(
                line.strip() for line in address.splitlines() if line.strip()
            ) or False
