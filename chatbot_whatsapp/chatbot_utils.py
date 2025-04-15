# -*- coding: utf-8 -*-
import base64, json, logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

class ChatbotHelper:
    """
    Funciones que el LLM podrá invocar mediante function‑calling.
    Iremos ampliándolas en las siguientes fases.
    """

    @staticmethod
    def get_product_price(env, product_name):
        product = env['product.product'].search(
            ['|', ('name', 'ilike', product_name),
                  ('default_code', '=', product_name)],
            limit=1)
        if not product:
            return {"found": False,
                    "message": f"No encontré {product_name} en el catálogo."}

        price = product.with_context(
            pricelist=env.ref('product.list0').id).price
        stock = product.qty_available

        return {"found": True,
                "name": product.display_name,
                "price": price,
                "stock": stock}

    @staticmethod
    def create_quotation(env, partner_phone, lines):
        # Sanitizá el teléfono como acostumbres en tu modelo
        partner = env['res.partner'].search(
            [('phone_sanitized', '=', partner_phone)], limit=1)
        if not partner:
            partner = env['res.partner'].create(
                {'name': partner_phone, 'phone': partner_phone})

        order_vals = {
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': env.ref(l['product_id']).id,
                'product_uom_qty': l['qty'],
            }) for l in lines]
        }
        order = env['sale.order'].create(order_vals)
        order.action_confirm()

        pdf_bytes = env.ref(
            'sale.action_report_saleorder')._render_qweb_pdf(order.id)[0]
        pdf_b64 = base64.b64encode(pdf_bytes).decode()

        return {"order_name": order.name, "pdf_b64": pdf_b64}
