from odoo import models, _
from odoo.exceptions import AccessError, UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        res = super().button_validate()

        processed_so_ids = set()

        for picking in self:
            if picking.picking_type_code != 'outgoing' or picking.state != 'done':
                continue

            # 1) vínculo estándar
            sale_orders = self.env['sale.order']
            if 'sale_id' in picking._fields:
                sale_orders = picking.sale_id

            # 2) fallback por sale_line_id
            if not sale_orders and 'sale_line_id' in self.env['stock.move']._fields:
                sale_orders = picking.move_ids_without_package.sale_line_id.order_id

            # 3) último fallback por origin
            if not sale_orders and picking.origin:
                sale_orders = self.env['sale.order'].search([('name', '=', picking.origin)])

            for sale_order in sale_orders:
                if not sale_order or sale_order.id in processed_so_ids:
                    continue

                processed_so_ids.add(sale_order.id)

                # Solo crear factura si realmente hay algo para facturar
                has_qty_to_invoice = any(line.qty_to_invoice > 0 for line in sale_order.order_line)
                if not has_qty_to_invoice:
                    continue

                # PRIORIDAD:
                # 1) vendedor asignado de la SO
                # 2) usuario que creó la SO
                invoice_user = sale_order.user_id or sale_order.create_uid

                if not invoice_user or not invoice_user.active:
                    raise UserError(_(
                        "No se puede crear la factura automática de la orden %s "
                        "porque no hay un usuario válido asignado."
                    ) % sale_order.name)

                try:
                    sale_order_env = sale_order.with_user(invoice_user).with_company(sale_order.company_id)
                    invoices = sale_order_env._create_invoices(final=True)

                    if invoices:
                        invoices.action_post()

                except AccessError as e:
                    raise UserError(_(
                        "La entrega se validó, pero no se pudo crear/publicar la factura "
                        "con el usuario '%s' en la orden '%s'.\n\n"
                        "Revisá permisos de Facturación y acceso a la compañía '%s'.\n\n"
                        "Detalle: %s"
                    ) % (
                        invoice_user.name,
                        sale_order.name,
                        sale_order.company_id.display_name,
                        str(e),
                    ))

        return res
