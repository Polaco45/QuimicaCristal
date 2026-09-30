# -*- coding: utf-8 -*-
"""Migración 18.0.1.33.0 — Reglas de oro: claridad con el cliente.

1) Prompt v7 (claudio_v7.md): sección "REGLAS DE ORO".
2) Config: ventana para que Claudio INICIE mensajes = 7:30 a 21:30 hora Argentina,
   todos los días; bidón nuevo = [DA0355] Bidón Plástico 20 lts a $3.500.
3) KB: UNA sola entrada oficial de dirección y horarios de la planta (había 3
   versiones distintas de horario) y se archivan las duplicadas. La KB de la ruta
   pierde el "+ IVA" (Joaco: el precio es el que es, no se menciona el IVA) y suma
   los bidones.
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

KB_PLANT_ID = 89
KB_PLANT_NAME = "Dirección y horarios de la planta (OFICIAL)"
KB_PLANT_CONTENT = """DIRECCIÓN Y HORARIOS DE LA PLANTA — FUENTE OFICIAL ÚNICA (no uses otros horarios)
- DIRECCIÓN: San Martín 2350, Río Cuarto (Córdoba). NO es Lamadrid y Mansilla ni ninguna otra dirección.
- HORARIO DE LA PLANTA (atención y retiros): lunes a viernes de 8:30 a 12:30 y de 15:30 a 19:30; sábados de 9:00 a 13:00. Domingos y feriados: cerrado.
- RETIRO EN PLANTA: solo con el pedido CONFIRMADO por Joaquín. Siempre decir día + fecha + este horario. El cliente trae sus bidones vacíos para el recambio (si no trae, cada bidón nuevo de 20 L sale $3.500) y el efectivo o el comprobante de la transferencia.
- REPARTO EN RÍO CUARTO Y LAS HIGUERAS: de lunes a viernes, SOLO por la mañana y NUNCA los jueves (ese día sale el camión de la ruta). El día lo confirma el equipo: no des hora exacta ni digas "el chofer te llama"."""

KB_TO_ARCHIVE = {
    68: "Horario 8:30 a 19:30 corrido: contradice el oficial (cortado).",
    13: "Horario 8:30 a 21:00 y reglas de fuera de horario: ahora lo maneja el sistema "
        "(ventana de contacto) y el horario oficial está en la #89.",
    33: "Duplicado del horario oficial (quedó en la #89).",
    25: "Duplicado de dirección y horario (quedó en la #89).",
    21: "Duplicado de la dirección (quedó en la #89).",
    62: "Duplicado de la dirección; su aclaración 'NO es Lamadrid y Mansilla' pasó a la #89.",
}

KB_ROUTE_NAME = "Ruta camión jueves"
KB_ROUTE_CONTENT = """RUTA DEL CAMIÓN MAYORISTA (desde el jueves 15/10/2026)
- Sale UN camión por semana, los JUEVES, a uno de 4 circuitos que rotan: Sur-Oeste → Norte → Este → Sur-Este. Cada pueblo tiene pasada cada 4 semanas.
- Circuitos y localidades:
  • Sur-Oeste: Holmberg, Santa Catalina, Las Vertientes, Sampacho, Suco, Chaján y Achiras (desvío opcional), Coronel Moldes, Vicuña Mackenna, Tosquita, Malena.
  • Norte: Espinillo, Coronel Baigorria, Alcira Gigena, Elena, Berrotarán, General Cabrera, General Deheza, Las Perdices, Dalmacio Vélez, Carnerillo, Chucul.
  • Este: Las Acequias, Reducción, Alejandro Roca, La Carlota, Chazón, Ucacha, Bengolea, Olaeta, Charras.
  • Sur-Este: San Basilio, Adelia María, Monte de los Gauchos.
- FECHA Y CIERRE: los da SIEMPRE get_route_info, textual (la preventa cierra el martes 18 h previo al jueves; si la salida está en rescate, el miércoles 12 h). NUNCA prometer otra fecha.
- PRECIO: Lista Mayorista de siempre, sin recargo por zona. No se menciona el IVA.
- MÍNIMO EN RUTA: $75.000 en productos (el flete y los bidones NO cuentan). FLETE: $9.000 si los productos no llegan a $99.000; desde $99.000 el envío es sin cargo. RESCATE (Plan B): envío sin cargo desde $75.000 + un producto de cortesía.
- BIDONES: el granel va en bidones de 20 L; si el cliente no tiene vacíos para el recambio, cada bidón nuevo sale $3.500. Decirlo SIEMPRE.
- COBRO: transferencia anticipada o efectivo contra entrega. Sin cuenta corriente.
- RÍO CUARTO (y Las Higueras, Banda Norte, Alberdi): reparto normal, de lunes a viernes SOLO por la mañana y NUNCA los jueves. Pedidos grandes o especiales: consultar a Joaco antes de comprometer la entrega.
- FUERA DE LOS 4 CIRCUITOS: se le pasa la lista y los precios, pero NO se ofrecen condiciones de envío; se marca fuera de zona y se escala a Joaco."""


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)

    # 1) Prompt v7
    if config:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'data', 'prompts', 'claudio_v7.md')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            config.write({'system_prompt': content, 'prompt_version': 'claudio_v7'})
            _logger.info("✅ MIGRATION 1.33.0: prompt v7 cargado (%s chars)", len(content))
        else:
            _logger.warning("⚠️ MIGRATION 1.33.0: no se encontró claudio_v7.md")

    # 2) Ventana de contacto + bidón
    if config:
        vals = {'work_hours_start': 7.5, 'work_hours_end': 21.5, 'bidon_price': 3500.0}
        bidon = env['product.product'].sudo().search([('default_code', '=', 'DA0355')], limit=1)
        if bidon:
            vals['bidon_product_id'] = bidon.id
        else:
            _logger.warning("⚠️ MIGRATION 1.33.0: no existe el producto DA0355 (bidón 20 L)")
        config.write(vals)
        _logger.info("✅ MIGRATION 1.33.0: ventana de contacto 7:30-21:30, bidón %s a $3.500",
                     bidon.display_name if bidon else '(sin producto)')

    # 3) KB
    Knowledge = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    plant = Knowledge.browse(KB_PLANT_ID)
    plant_vals = {'name': KB_PLANT_NAME, 'content': KB_PLANT_CONTENT,
                  'priority': 100, 'active': True}
    if plant.exists():
        plant.write(plant_vals)
    else:
        plant = Knowledge.create(dict(plant_vals, category='regla_negocio'))
    _logger.info("✅ MIGRATION 1.33.0: KB oficial de planta (id=%s)", plant.id)

    lines = []
    for kb_id, reason in KB_TO_ARCHIVE.items():
        kb = Knowledge.browse(kb_id)
        if not kb.exists():
            lines.append(f"  #{kb_id}: no existe (se omite)")
        elif kb.active:
            kb.active = False
            lines.append(f"  #{kb_id} '{kb.name}' ARCHIVADA — {reason}")
        else:
            lines.append(f"  #{kb_id} '{kb.name}' ya estaba archivada — {reason}")
    _logger.info("✅ MIGRATION 1.33.0: KB archivadas:\n%s", "\n".join(lines))

    route = Knowledge.search([('name', '=', KB_ROUTE_NAME)], limit=1)
    if route:
        route.write({'content': KB_ROUTE_CONTENT, 'active': True})
        _logger.info("✅ MIGRATION 1.33.0: KB '%s' actualizada (sin IVA, con bidones)",
                     KB_ROUTE_NAME)
