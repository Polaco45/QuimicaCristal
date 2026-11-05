# -*- coding: utf-8 -*-
"""Migración 18.0.1.60.0 — Claudio vende bien los combos para la casa.

Joaco, 05/11/2026: "no es coherente a la hora de ofrecer los combos minoristas, no sabe ni
qué tienen, mal vendedor". El catálogo con lo que trae cada combo ahora lo arma el código
(services/cf_combos.py) y llega en el bloque "COMBOS PARA LA CASA". Acá se cambian las
reglas de venta del prompt (sección 4b), se saca el pedido de permiso de avisos (desde el
04/11 los avisos llegan a todos) y se corrigen restos de "camión los miércoles" (es el jueves
desde el 03/11). Reemplazos textuales e idempotentes; los que no encuentra los avisa en el log.
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

OLD_LADDER = (
    "- **Escalera de venta, de mayor a menor — UNA oferta por mensaje:** 1) el **combo** que incluye "
    "lo que pide (Casa Completa $39.900, Limpieza Total $29.900, Lavadero Completo $18.900, Cocina "
    "$15.400, Casa Limpia $9.900, Ropa $6.490, Limpieza Diaria $5.990; Pileta $32.900 en temporada); "
    "2) si dice que no, el **tamaño más grande** (el de 5 lts rinde más por litro); 3) si no, **un "
    "complemento**. Si le falta poco para el envío gratis, decíselo.")
NEW_LADDER = (
    "- **Combos para la casa — vendelos como un vendedor que los conoce:** lo que trae cada uno, "
    "sus aromas/colores, el precio, cuánto sale suelto y cuánto ahorra están en el bloque "
    "**COMBOS PARA LA CASA**. Cuando pregunta por un combo, viene del anuncio de combos o pide "
    "varias cosas de limpieza para la casa: 1) **recomendá UNO** según lo que necesita (ropa → Ropa o "
    "Lavadero Completo; cocina → Cocina; toda la casa → Casa Completa o Limpieza Total; pisos y baño "
    "→ Casa Limpia; pileta → Pileta); 2) en **un mensaje corto** decile qué trae (la lista del "
    "bloque, sin inventar ni resumir en \"productos para toda la casa\"), el precio y **cuánto "
    "ahorra** contra comprarlo suelto, y el envío (gratis desde $65.000; si no llega, cuánto le falta "
    "o el retiro sin cargo); 3) si tiene aromas o colores a elegir, preguntá en **una línea** cuál "
    "prefiere; 4) cotizalo con `create_sale_order` (product_id del combo + `choices`) y pasale el "
    "`client_summary`. Si duda entre dos, mostrale la diferencia de precio y qué suma el más grande. "
    "**Nunca** digas que no sabés qué trae ni lo consultes con Joaco, y no ofrezcas un combo marcado "
    "⛔ HOY NO OFRECER. Si nombra un combo, ya sabés que es para su casa: no le preguntes si revende.\n"
    "- **Escalera de venta, de mayor a menor — UNA oferta por mensaje:** 1) el **combo** que incluye "
    "lo que pide; 2) si dice que no, el **tamaño más grande** (el de 5 lts rinde más por litro); 3) si "
    "no, **un complemento**. Si le falta poco para el envío gratis, decíselo.")

REPLACEMENTS = [
    (OLD_LADDER, NEW_LADDER),
    # Avisos: desde el 04/11 no se pide permiso (llegan a todos; el que no quiere se da de baja).
    ("- **Al cerrar:** si su bloque dice que nunca se le preguntó, pedile el permiso de avisos "
     "(`set_promo_consent`).",
     "- **Avisos:** no le preguntes si quiere avisos o promos: le llegan a todos. Si pide no recibir "
     "más promos, `set_promo_consent(accepted=false)`."),
    ("- **Avisos por WhatsApp:** si su bloque dice \"todavía no se le preguntó\", al cerrar una "
     "cotización (o si pide que le avisen promos) preguntá UNA vez, en media línea: \"¿Querés que te "
     "avisemos por acá cuando se te esté por terminar algo y cuando haya promos?\". Sí → "
     "`set_promo_consent(accepted=true)`. Si pide no recibir promos → "
     "`set_promo_consent(accepted=false)` (no es \"No contactar\": sigue comprando normal). Nunca lo "
     "preguntes dos veces ni en medio de un reclamo.",
     "- **Avisos por WhatsApp:** no se pide permiso: los avisos y promos le llegan a todos. Si pide no "
     "recibir promos → `set_promo_consent(accepted=false)` (no es \"No contactar\": sigue comprando "
     "normal)."),
    # La ruta sale los JUEVES desde el 03/11 (restos de la v9).
    ("adonde llega nuestro camión los miércoles**", "adonde llega nuestro camión los jueves**"),
    ("la planta abre todos los días hábiles (también el miércoles) en su horario oficial para retirar",
     "la planta abre todos los días hábiles (también el jueves) en su horario oficial para retirar"),
    ("(b) **pueblos de la ruta del camión**, el miércoles que pasa el camión por su circuito",
     "(b) **pueblos de la ruta del camión**, el jueves que pasa el camión por su circuito"),
    ("*\"Pasamos por Sampacho el miércoles 14/10; tomamos pedidos hasta el lunes 12/10 a las 18 h.\"*",
     "*\"Pasamos por Sampacho el jueves 12/11; tomamos pedidos hasta el miércoles 11/11 a las 18 h.\"*"),
]


def apply(text):
    """Devuelve (texto, aplicados, faltantes)."""
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
    if not config or not config.system_prompt:
        _logger.info("MIGRATION 1.60.0: sin config activa / prompt, no hay nada que cambiar")
        return
    text, done, missing = apply(config.system_prompt)
    if text != config.system_prompt:
        config.system_prompt = text
    _logger.info("✅ MIGRATION 1.60.0: prompt (%s) — %s reemplazos ok", config.prompt_version, len(done))
    for m in missing:
        _logger.warning("⚠️ MIGRATION 1.60.0: no encontré en el prompt: %s…", m)
