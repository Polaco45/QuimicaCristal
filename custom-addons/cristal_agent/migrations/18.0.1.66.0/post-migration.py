# -*- coding: utf-8 -*-
"""Migración 18.0.1.66.0 — Conversión punto 10 (12/11/2026, Joaco: "Sí, sumalo").

Claudio manda facturas (generate_invoice_pdf), dice el saldo (search_invoices trae
saldo_pendiente y saldo_vencido) y toma los comprobantes de transferencia
(register_payment_receipt: los guarda y le deja la verificación a Sergio, user 2). Nunca da
un pago por acreditado. Reemplazo textual e idempotente en el prompt vivo.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

REPLACEMENTS = [
    ("Los datos para transferir (Brubank / alias / CBU) los tenés en la base de conocimiento — pasalos TEXTUAL, nunca inventes un CBU.",
     "Los datos para transferir (Brubank / alias / CBU) los tenés en la base de conocimiento — pasalos TEXTUAL, nunca inventes un CBU.\n- **Facturas, saldo y comprobantes (lo resolvés vos, sin pasarlo a Joaco):** si pide una factura → `search_invoices` y `generate_invoice_pdf`, y mandala con `send_whatsapp` (una línea + el PDF). Si pregunta cuánto debe → `search_invoices(only_unpaid=true)`: decí el `saldo_pendiente` (y cuánto está vencido) y pasale los datos para transferir. Si manda el **comprobante** de una transferencia (foto o PDF) → `register_payment_receipt` con el monto que figura y el pedido si corresponde, y decile *\"Recibimos el comprobante, lo verificamos y le confirmamos.\"* **Nunca** digas que el pago está acreditado ni que la deuda quedó saldada: eso lo confirma administración."),
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        return
    if not config.payment_receipt_user_id:
        user = env['res.users'].browse(2).exists()
        if user and 'sergio' in (user.name or '').lower():
            config.payment_receipt_user_id = user.id
    text = config.system_prompt or ''
    for old, new in REPLACEMENTS:
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new)
        else:
            _logger.warning("⚠️ MIGRATION 1.66.0: no encontré en el prompt: %s…", old[:60])
    if text != (config.system_prompt or ''):
        config.system_prompt = text
        _logger.info("✅ MIGRATION 1.66.0: prompt actualizado (facturas, saldo, comprobantes)")
