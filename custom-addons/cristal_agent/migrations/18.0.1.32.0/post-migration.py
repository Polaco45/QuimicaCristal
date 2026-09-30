# -*- coding: utf-8 -*-
"""Migración 18.0.1.32.0 — Ruta del camión mayorista (Fase 1).

1) Recarga el prompt v6 (claudio_v6.md).
2) Config: producto de flete (FLETE-ZONA).
3) Vincula (defensivo) cada circuito con su etiqueta de contacto.
4) Genera las salidas de las próximas 12 semanas.
5) Backfill de truck_circuit_id: la ETIQUETA de circuito manda; la ciudad solo si
   el contacto no tiene etiqueta. Nunca se pisa una etiqueta existente. Los
   contactos con circuito quedan con agent_zone = 'ruta_camion'.
6) KB: crea "Ruta camión jueves" y archiva 3, 4, 12, 15, 43, 53 y 96 (contradicen
   la ruta). El listado con el motivo queda en el log y en el CHANGELOG.
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

CIRCUIT_TAGS = {
    'Sur-Oeste': 'Ruta Sur-Oeste',
    'Norte': 'Ruta Norte',
    'Este': 'Ruta Este',
    'Sur-Este': 'Ruta Sur-Este',
}

KB_TO_ARCHIVE = {
    3: "Mínimo $50.000 para todos: en la ruta el mínimo es $75.000 + IVA de productos "
       "(el mínimo ahora depende de la zona; está en el prompt v6 y en 'Ruta camión jueves').",
    4: "Pide 'facturar $50.000/mes' y cobertura 'Río Cuarto + 200 km': contradice 'nunca "
       "preguntes facturación' y las zonas nuevas (4 circuitos / fuera de circuito).",
    12: "Dice que los audios no se procesan (la transcripción está activa) y takeover de 1 h "
        "(hoy 12 h); la política de escalamiento vive en el prompt v6.",
    15: "Solo Río Cuarto/Las Higueras y 'NO mandar lista fuera de zona': contradice la ruta "
        "(ahora se entrega en los pueblos) y la regla de mandar la lista siempre.",
    43: "Zona de entrega solo Río Cuarto y Las Higueras: reemplazada por la ruta del camión.",
    53: "Compra mínima $50.000 'para todo': en la ruta el mínimo es $75.000 + IVA.",
    96: "Entregas solo por la mañana: su contenido pasó a 'Ruta camión jueves' y al prompt v6, "
        "que además agregan que Río Cuarto no tiene reparto los jueves.",
}

KB_ROUTE_NAME = "Ruta camión jueves"
KB_ROUTE_CONTENT = """RUTA DEL CAMIÓN MAYORISTA (desde el jueves 15/10/2026)
- Sale UN camión por semana, los JUEVES, a uno de 4 circuitos que rotan: Sur-Oeste → Norte → Este → Sur-Este. Cada pueblo tiene pasada cada 4 semanas.
- Circuitos y localidades:
  • Sur-Oeste: Holmberg, Santa Catalina, Las Vertientes, Sampacho, Suco, Chaján y Achiras (desvío opcional), Coronel Moldes, Vicuña Mackenna, Tosquita, Malena.
  • Norte: Espinillo, Coronel Baigorria, Alcira Gigena, Elena, Berrotarán, General Cabrera, General Deheza, Las Perdices, Dalmacio Vélez, Carnerillo, Chucul.
  • Este: Las Acequias, Reducción, Alejandro Roca, La Carlota, Chazón, Ucacha, Bengolea, Olaeta, Charras.
  • Sur-Este: San Basilio, Adelia María, Monte de los Gauchos.
- FECHA Y CIERRE: los da SIEMPRE get_route_info (la preventa cierra el martes 18 h previo al jueves; si la salida está en rescate, el miércoles 12 h). NUNCA prometer otra fecha.
- PRECIO: Lista Mayorista de siempre, sin recargo por zona.
- MÍNIMO EN RUTA: $75.000 + IVA de productos (el flete NO cuenta). FLETE: $9.000 + IVA si los productos no llegan a $99.000 + IVA; desde $99.000 + IVA el envío es sin cargo. RESCATE (Plan B): envío sin cargo desde $75.000 + un producto de cortesía.
- COBRO: transferencia anticipada o efectivo contra entrega. Sin cuenta corriente.
- RÍO CUARTO (y Las Higueras, Banda Norte, Alberdi): reparto normal, SOLO por la mañana y NUNCA los jueves. No comprometer horarios exactos ni 'te llama el chofer'; pedidos grandes o especiales: consultar a Joaco antes de comprometer la entrega.
- FUERA DE LOS 4 CIRCUITOS: se le pasa la lista y los precios, pero NO se ofrecen condiciones de envío; se marca fuera de zona y se escala a Joaco."""


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)

    # 1) Prompt v6
    if config:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'data', 'prompts', 'claudio_v6.md')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            config.write({'system_prompt': content, 'prompt_version': 'claudio_v6'})
            _logger.info("✅ MIGRATION 1.32.0: prompt v6 cargado (%s chars)", len(content))
        else:
            _logger.warning("⚠️ MIGRATION 1.32.0: no se encontró claudio_v6.md")

    # 2) Producto de flete
    if config and not config.route_freight_product_id:
        freight = env['product.product'].sudo().search(
            [('default_code', '=', 'FLETE-ZONA')], limit=1)
        if freight:
            config.write({'route_freight_product_id': freight.id})
            _logger.info("✅ MIGRATION 1.32.0: producto de flete = %s (id=%s)",
                         freight.display_name, freight.id)
        else:
            _logger.warning("⚠️ MIGRATION 1.32.0: no existe el producto FLETE-ZONA")

    # 3) Etiqueta de cada circuito (por si el XML no la resolvió)
    Circuit = env['cristal.agent.circuit'].sudo()
    Category = env['res.partner.category'].sudo()
    for circuit in Circuit.search([]):
        if circuit.partner_category_id:
            continue
        cat = Category.search([('name', '=', CIRCUIT_TAGS.get(circuit.name, ''))], limit=1)
        if cat:
            circuit.partner_category_id = cat.id
        else:
            _logger.warning("⚠️ MIGRATION 1.32.0: el circuito %s no tiene etiqueta", circuit.name)

    # 4) Salidas de las próximas 12 semanas
    created = env['cristal.agent.route.departure'].sudo().generate_upcoming(weeks=12)
    _logger.info("✅ MIGRATION 1.32.0: %s salidas generadas", created)

    # 5) Backfill de circuitos + agent_zone
    counts = Circuit.action_backfill_truck_circuits()
    _logger.info("✅ MIGRATION 1.32.0: backfill de circuitos %s", counts)
    Partner = env['res.partner'].sudo()
    in_route = Partner.search([('truck_circuit_id', '!=', False),
                               ('agent_zone', '!=', 'ruta_camion')])
    in_route.write({'agent_zone': 'ruta_camion'})
    fz = Category.search([('name', '=', 'Fuera de zona')], limit=1)
    with_fz = Partner.search_count([('truck_circuit_id', '!=', False),
                                    ('category_id', 'in', fz.ids)]) if fz else 0
    _logger.info("✅ MIGRATION 1.32.0: %s contactos pasan a agent_zone=ruta_camion. "
                 "%s contactos de circuito conservan la etiqueta 'Fuera de zona' (no se "
                 "tocó: los excluye del broadcast semanal).", len(in_route), with_fz)

    # 6) Base de conocimiento
    Knowledge = env['cristal.agent.knowledge'].sudo().with_context(active_test=False)
    entry = Knowledge.search([('name', '=', KB_ROUTE_NAME)], limit=1)
    vals = {'name': KB_ROUTE_NAME, 'content': KB_ROUTE_CONTENT,
            'category': 'regla_negocio', 'priority': 100, 'active': True}
    if entry:
        entry.write(vals)
        _logger.info("↻ MIGRATION 1.32.0: KB '%s' actualizada (id=%s)", KB_ROUTE_NAME, entry.id)
    else:
        entry = Knowledge.create(vals)
        _logger.info("✅ MIGRATION 1.32.0: KB '%s' creada (id=%s)", KB_ROUTE_NAME, entry.id)

    lines = []
    for kb_id, reason in KB_TO_ARCHIVE.items():
        kb = Knowledge.browse(kb_id)
        if not kb.exists():
            lines.append(f"  #{kb_id}: no existe (se omite)")
            continue
        if kb.active:
            kb.active = False
            lines.append(f"  #{kb_id} '{kb.name}' ARCHIVADA — {reason}")
        else:
            lines.append(f"  #{kb_id} '{kb.name}' ya estaba archivada — {reason}")
    _logger.info("✅ MIGRATION 1.32.0: KB archivadas:\n%s", "\n".join(lines))
