# -*- coding: utf-8 -*-
"""Migración 18.0.1.75.0 — Joaco (17/11/2026), sobre los contactos que trae la pauta:

- "Si son para la casa, que los derive a la web o que los atienda simple."
- "Si son mayoristas, a todos los atiende igual; solo que a los que nuestras rutas no cubren
  les ofrece retiro con comisionista o que vengan a nuestro local."

Reemplazos textuales e idempotentes sobre el prompt vivo.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

CF_OLD = ("es **consumidor final**: **atendelo y vendele vos**, ya **no** se lo deriva al "
          "local. Ante la duda, sigue valiendo: es mayorista.")
CF_NEW = (
    "es **consumidor final**. Ante la duda, sigue valiendo: es mayorista.\n"
    "- **ATENCIÓN SIMPLE (Joaco, 17/11/2026):** al que compra para su casa se lo atiende en "
    "**pocos mensajes**. En tu primera respuesta, en dos líneas: que puede comprar directo en "
    "**quimicacristal.com.ar** (ahí están los precios, los combos y el envío en Río Cuarto) o "
    "pasar por el local (San Martín 2350, horario oficial), y que si prefiere le tomás el "
    "pedido por acá. Si pide algo concreto, **cotizalo UNA vez y cerrá**. **No** le hagas "
    "preguntas de calificación mayorista (rubro, litros por mes, cómo nos conoció), **no** le "
    "mandes la lista mayorista y **no** insistas: como mucho **una** sugerencia. Si no "
    "contesta, no lo sigas. Lo que sigue es cómo cotizarle y confirmarle cuando sí quiere "
    "comprar por acá:")

FZ_OLD = ("Fuera de zona: retiro en planta o transporte a cargo del cliente, nunca "
          "\"Joaquín le coordina el envío\".")
FZ_NEW = (
    "Fuera de nuestras rutas (y pueblos con el camión **pausado**): es un mayorista como "
    "cualquier otro —misma lista, mismos precios y combos—; lo único que cambia es la "
    "entrega: **retiro en el local** (San Martín 2350) o que lo mande a buscar con un "
    "**comisionista o transporte** de su confianza, a su cargo. Cotizá con "
    "`delivery_mode='retiro'`. Nunca \"Joaquín le coordina el envío\" y **no escales a Joaco "
    "por ser de fuera de zona**.")

REPLACEMENTS = [(CF_OLD, CF_NEW), (FZ_OLD, FZ_NEW)]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config or not config.system_prompt:
        return
    text = config.system_prompt
    for old, new in REPLACEMENTS:
        if new in text:
            continue
        if old in text:
            text = text.replace(old, new)
        else:
            _logger.warning("⚠️ MIGRATION 1.75.0: no encontré en el prompt: %s…", old[:60])
    if text != config.system_prompt:
        config.system_prompt = text
        _logger.info("✅ MIGRATION 1.75.0: prompt actualizado (consumidor final simple, fuera de ruta)")
