from odoo import models

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        res = super().button_validate()

        # Ojo: button_validate a veces devuelve un wizard (backorder / immediate transfer)
        # y el picking todavía no queda en done en ese mismo request.
        # Por eso chequeamos state == done luego del super.

        # Evitar crear duplicado si en el mismo validate entran varios pickings
        processed_so_ids = set()

        for picking in self:
            if picking.picking_type_code != 'outgoing' or picking.state != 'done':
                continue

            # 1) Primero intentamos con el vínculo estándar (sale_stock)
            sale_orders = self.env['sale.order']
            if 'sale_id' in picking._fields:
                sale_orders = picking.sale_id

            # 2) Fallback: inferir desde las líneas de venta vinculadas a los movimientos
            if not sale_orders and 'sale_line_id' in self.env['stock.move']._fields:
                sale_orders = picking.move_ids_without_package.sale_line_id.order_id

            # 3) Último fallback: origin == nombre de SO (lo que estabas usando)
            if not sale_orders and picking.origin:
                sale_orders = self.env['sale.order'].search([('name', '=', picking.origin)])

            for sale_order in sale_orders:
                if not sale_order or sale_order.id in processed_so_ids:
                    continue

                # Crear una nueva factura SOLO si hay algo realmente por facturar.
                # Esto permite múltiples facturas en entregas parciales.
                # (Evita el bug anterior: "si ya existe una factura, no hagas nada")
                has_qty_to_invoice = any(line.qty_to_invoice > 0 for line in sale_order.order_line)
                if not has_qty_to_invoice:
                    processed_so_ids.add(sale_order.id)
                    continue

                invoices = sale_order._create_invoices(final=True)
                if invoices:
                    invoices.action_post()

                processed_so_ids.add(sale_order.id)
        return res
