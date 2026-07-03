from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    receiver_name = fields.Char(
        string="Recibido por",
        help="Nombre y aclaración de la persona que recibió la entrega. "
        "Se completa al firmar y se imprime en el remito de entrega.",
        copy=False,
        tracking=True,
    )
