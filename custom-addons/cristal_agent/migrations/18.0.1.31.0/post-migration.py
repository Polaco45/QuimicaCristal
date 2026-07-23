# -*- coding: utf-8 -*-
"""
Migración 18.0.1.31.0 — Iteración comercial:
- Recarga el prompt v5 (fuera de zona con retiro por comisionista + escalación
  solo por chat interno).
- Apaga los avisos a Joaco por WhatsApp (ahora escala solo al canal interno).
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if not config:
        return

    # 1) Recargar prompt v5
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v5.md')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        config.write({'system_prompt': content, 'prompt_version': 'claudio_v5'})
        _logger.info("✅ MIGRATION 1.31.0: prompt v5 recargado (%s chars)", len(content))
    else:
        _logger.warning("⚠️ MIGRATION 1.31.0: no se encontró claudio_v5.md")

    # 2) Escalaciones SOLO por chat interno — cortar los avisos por WhatsApp a Joaco
    try:
        config.write({'notify_owner_via_whatsapp': False})
        _logger.info("✅ MIGRATION 1.31.0: notify_owner_via_whatsapp = False")
    except Exception as e:
        _logger.warning("MIGRATION 1.31.0: no se pudo apagar notify_owner_via_whatsapp: %s", e)

    # 3) Entradas de KB self-service (idempotentes): datos de transferencia y
    #    punto de retiro / horarios de planta. Así el bot los da solo y no escala
    #    ni inventa (caso Juliana: el bot inventó un CBU que no funcionaba).
    Knowledge = env['cristal.agent.knowledge'].sudo()

    def _upsert_knowledge(name, content, category='politica_comercial', priority=100):
        entry = Knowledge.search([('name', 'ilike', name)], limit=1)
        vals = {
            'name': name, 'content': content, 'category': category,
            'priority': priority, 'active': True,
        }
        if entry:
            entry.write({'content': content, 'active': True, 'priority': priority})
            _logger.info("↻ MIGRATION 1.31.0: KB '%s' actualizada (id=%s)", name, entry.id)
        else:
            try:
                new = Knowledge.create(vals)
                _logger.info("✅ MIGRATION 1.31.0: KB '%s' creada (id=%s)", name, new.id)
            except Exception as e:
                _logger.warning("MIGRATION 1.31.0: no se pudo crear KB '%s': %s", name, e)

    _upsert_knowledge(
        "Datos para transferencia bancaria",
        "DATOS PARA TRANSFERENCIA (pasalos TEXTUAL, NUNCA inventes un CBU/alias). "
        "Cuando el cliente pide los datos para transferir, mandá EXACTAMENTE esto:\n"
        "Titular: Química Cristal – Crilim S.A.S.\n"
        "Banco: Brubank\n"
        "Alias: crilim.sas\n"
        "CBU: 1430001725040102970011\n"
        "CUIT: 30-71855127-3\n"
        "N° de cuenta: 2504010297001\n"
        "Pedile que te mande el comprobante por acá una vez que transfiera. Si por "
        "algún motivo no tenés estos datos a mano, NO improvises ni inventes: usá SOLO estos.",
    )

    _upsert_knowledge(
        "Punto de retiro y horarios de planta",
        "PUNTO DE RETIRO Y HORARIOS DE PLANTA (para retiro por comisionista / clientes "
        "fuera de zona, o quien pregunte dónde/cuándo retirar).\n"
        "Dirección de la planta: San Martín 2350, Río Cuarto (Córdoba).\n"
        "Horarios de atención de la planta: Lunes a Viernes de 8:30 a 12:30 y de 15:30 "
        "a 19:30; Sábados de 9:00 a 13:00.\n"
        "Cuando pregunten dónde retirar o en qué horario, pasales esto. NO inventes "
        "horarios ni direcciones distintas.",
    )
