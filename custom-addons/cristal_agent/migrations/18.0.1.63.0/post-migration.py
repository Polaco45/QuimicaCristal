# -*- coding: utf-8 -*-
"""Migración 18.0.1.63.0 — Decisiones de conversión de Joaco (10/11/2026).

- Punto 2: el 20% de primera compra vale en Río Cuarto / Las Higueras **o si retira en el
  local** (la tool create_sale_order ya lo deja con delivery_mode='retiro').
- Punto 5: Claudio confirma solo hasta $200.000 (antes $150.000) y siempre con stock.
- Punto 6: descuentos solo los estipulados (20% de primera compra, niveles, referidos y
  ofertas vigentes). No se negocia y no se escala por un pedido de descuento.
- Punto 10: pago solo efectivo contra entrega o transferencia (sin Mercado Pago, tarjeta
  ni link de pago).

Reemplazos textuales e idempotentes sobre el prompt vivo; los que no encuentra los avisa en
el log. El archivo claudio_v10.md tiene los mismos cambios.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

REPLACEMENTS = [
    # Punto 2 — regla de oro 11
    ("11. **20% OFF DE PRIMERA COMPRA: SOLO RÍO CUARTO / LAS HIGUERAS.** A los clientes de la "
     "**ruta del camión** (Sampacho, Coronel Moldes, Vicuña Mackenna, etc.) y a los de **fuera "
     "de zona**, **NUNCA** se lo ofrezcas, ni lo menciones, ni pases `discount_percent`.",
     "11. **20% OFF DE PRIMERA COMPRA: SOLO RÍO CUARTO / LAS HIGUERAS, O SI RETIRA EN EL "
     "LOCAL.** A los clientes de la **ruta del camión** (Sampacho, Coronel Moldes, Vicuña "
     "Mackenna, etc.) y a los de **fuera de zona**, con envío **NUNCA** se lo ofrezcas ni pases "
     "`discount_percent`. **Si retiran el pedido en el local (San Martín 2350, Río Cuarto), sí "
     "les corresponde**: cotizá con `delivery_mode='retiro'` y `discount_percent=20`."),
    ("**20% OFF en la PRIMERA compra — SOLO para clientes de Río Cuarto / Las Higueras** "
     "(regla de oro 11).",
     "**20% OFF en la PRIMERA compra — SOLO para clientes de Río Cuarto / Las Higueras o si "
     "retiran en el local** (regla de oro 11)."),
    ("SOLO si el cliente **NUNCA compró** y es de **Río Cuarto / Las Higueras**.",
     "SOLO si el cliente **NUNCA compró** y es de **Río Cuarto / Las Higueras** (o retira en el "
     "local)."),
    # Punto 6 — descuentos
    ("El único descuento que aplicás solo es el **20% de primera compra (solo Río Cuarto / Las "
     "Higueras)**; cualquier otro descuento/plazo especial → escalá a Joaco.",
     "**Descuentos: SOLO los estipulados** — el **20% de primera compra** (Río Cuarto / Las "
     "Higueras o retiro en el local), los niveles Plata/Oro y el crédito por referido (se aplican "
     "solos) y los precios de las **ofertas vigentes** (`search_offers`). **No hay otros "
     "descuentos ni plazos y no negociás.** Si pide rebaja, decile amable que son precios de "
     "fábrica y, si hay, ofrecé la oferta vigente o lo que le falta para el envío sin cargo. **No "
     "escales a Joaco por un pedido de descuento.**"),
    ("cuenta corriente o descuento/plazo fuera de política,",
     "cuenta corriente o plazo fuera de política (los descuentos no se negocian ni se escalan),"),
    # Punto 10 — pagos
    ("**NUNCA cuenta corriente ni cheque** (tampoco en la ruta).",
     "**NUNCA cuenta corriente, cheque, tarjeta, Mercado Pago ni link de pago** (tampoco en la "
     "ruta)."),
    # Punto 5 — stock al confirmar
    ("4. **Confirmá vos:** `confirm_order(partner_id, order_id, payment)`.",
     "4. **Confirmá vos:** `confirm_order(partner_id, order_id, payment)` — confirma hasta "
     "$200.000 y **solo si hay stock** de lo de distribución (lo que fabricamos se hace a "
     "pedido). Si dice que falta stock, **no confirmes ni prometas fecha**: ofrecé una "
     "alternativa con stock o escalá."),
]


def apply(text):
    done, missing = [], []
    for old, new in REPLACEMENTS:
        if new in text:
            done.append(old[:40])
        elif old in text:
            text = text.replace(old, new)
            done.append(old[:40])
        else:
            missing.append(old[:60])
    return text, done, missing


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        _logger.info("MIGRATION 1.63.0: sin config activa")
        return
    # Punto 5: tope de confirmación automática $200.000.
    if (config.auto_confirm_max_amount or 0.0) < 200000.0:
        config.auto_confirm_max_amount = 200000.0
    if config.system_prompt:
        text, done, missing = apply(config.system_prompt)
        if text != config.system_prompt:
            config.system_prompt = text
        _logger.info("✅ MIGRATION 1.63.0: prompt (%s) — %s reemplazos ok",
                     config.prompt_version, len(done))
        for m in missing:
            _logger.warning("⚠️ MIGRATION 1.63.0: no encontré en el prompt: %s…", m)
