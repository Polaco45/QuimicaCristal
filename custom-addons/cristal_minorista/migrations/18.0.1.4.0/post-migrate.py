# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields


def migrate(cr, version):
    """Clientes con lista L.E o Mayorista, etiquetados Mayorista o que compran a precio mayorista dejan de figurar como
    consumidor final (29/10/2026: 868 con etiqueta y 129 con pedidos mayoristas estaban como CF)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['cristal.minorista.engine']._refresh_wholesale_buyers(fields.Datetime.now() - timedelta(days=730))
    partners = env['res.partner'].with_context(active_test=False).search([])
    env.add_to_compute(partners._fields['cristal_customer_type'], partners)
    env.flush_all()
    # Pedidos de consumidor final ya confirmados y entregados: fecha de entrega por los remitos hechos
    for order in env["sale.order"].search([("cristal_is_cf", "=", True), ("state", "=", "sale"), ("cristal_delivered_date", "=", False)]):
        outs = order.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")
        if outs and all(p.state in ("done", "cancel") for p in outs):
            order.cristal_delivered_date = max(outs.filtered(lambda p: p.state == "done").mapped("date_done") or [order.date_order]).date()
