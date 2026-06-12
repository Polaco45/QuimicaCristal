# -*- coding: utf-8 -*-
"""
Migración 18.0.1.11.0 — Optimización de costo + formas + debounce + zona.

- Recarga el prompt mayorista v3.2 (tono endurecido + preguntas agrupadas +
  captura de ciudad/zona) en la config activa.
- Setea defaults de los campos nuevos (debounce_seconds=10,
  escalate_client_msgs_to_strong=False) por si el upgrade no los backfillea.
- Asegura que exista la etiqueta de contacto "Fuera de zona" para el
  auto-etiquetado geográfico.
"""
import logging
import os

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("⚙️  MIGRATION 1.11.0: prompt v3.2 + defaults debounce/zona")

    cr.execute("SELECT id FROM cristal_agent_config WHERE active=true LIMIT 1")
    row = cr.fetchone()
    if not row:
        _logger.warning("MIGRATION 1.11.0: no hay config activa, salteo")
        return
    config_id = row[0]

    # 1. Recargar prompt mayorista v3.2
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'data', 'prompts', 'claudio_v3_2.md'
    )
    if os.path.exists(prompt_path):
        with open(prompt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        cr.execute(
            "UPDATE cristal_agent_config "
            "SET system_prompt = %s, prompt_version = %s WHERE id = %s",
            (content, 'claudio_v3_2', config_id),
        )
        _logger.info("✅ Prompt mayorista v3.2 recargado (%s chars)", len(content))
    else:
        _logger.warning("MIGRATION 1.11.0: no se encontró claudio_v3_2.md")

    # 2. Defaults de campos nuevos (solo si quedaron NULL tras el upgrade)
    cr.execute(
        "UPDATE cristal_agent_config "
        "SET debounce_seconds = COALESCE(debounce_seconds, 10), "
        "    escalate_client_msgs_to_strong = COALESCE(escalate_client_msgs_to_strong, false) "
        "WHERE id = %s",
        (config_id,),
    )

    # 3. Asegurar etiqueta "Fuera de zona" (vía ORM, robusto ante jsonb/idiomas)
    try:
        env = api.Environment(cr, SUPERUSER_ID, {})
        Cat = env['res.partner.category']
        if not Cat.search([('name', '=', 'Fuera de zona')], limit=1):
            Cat.create({'name': 'Fuera de zona'})
            _logger.info("✅ Etiqueta 'Fuera de zona' creada")
    except Exception as e:
        _logger.warning("No se pudo crear etiqueta 'Fuera de zona': %s", e)
