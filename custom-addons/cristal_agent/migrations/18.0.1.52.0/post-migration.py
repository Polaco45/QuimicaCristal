# -*- coding: utf-8 -*-
"""Migración 18.0.1.52.0 — Ciclo de vida del mayorista, atribución y cross-sell con datos.

Joaco (02/11/2026): "automatizar todo el mayorista". Primer bloque del plan:
- Prompt v8 (suggest_products + etapa del cliente).
- Motor de ciclo de vida en modo EN SECO (no manda nada): se calcula la etapa de todos
  los mayoristas y se registra qué acción les tocaría.
- Origen de los contactos de los últimos 120 días a partir de su primer mensaje de
  WhatsApp (códigos y frases prellenadas de los anuncios).
"""
import logging
import os
import re
from datetime import timedelta

from odoo import api, fields, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        'data', 'prompts', 'claudio_v8.md')
    if config and os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            config.write({'system_prompt': f.read(), 'prompt_version': 'claudio_v8'})
        _logger.info("✅ MIGRATION 1.52.0: prompt v8 cargado")
    if config and not config.lifecycle_mode:
        config.lifecycle_mode = 'dry_run'

    # Frases prellenadas que usan hoy los anuncios (los creativos de Meta no se pueden
    # editar; mientras no haya códigos en los anuncios, se reconocen por la frase).
    Param = env['ir.config_parameter'].sudo()
    if not Param.get_param('cristal_agent.origin_phrases'):
        Param.set_param('cristal_agent.origin_phrases', "\n".join([
            "MAY-LISTA | Quiero Lista de Precios y me gustaria pasar un Pedido",
            "MAY-INFO | Quiero más información",
            "CF-CLORO | Quiero la promo de Cloro 6kg",
            "CF-COMBO | Quiero el combo",
            "ORG-IG | Me gustaría conseguir más información sobre esto",
        ]))

    # Origen de los contactos recientes: su primer mensaje entrante de WhatsApp.
    try:
        Life = env['cristal.agent.lifecycle']
        partners = Life.mayorista_partners().filtered(
            lambda p: not p.agent_origin_code and (p.mobile or p.phone)
            and p.create_date >= fields.Datetime.now() - timedelta(days=120))
        WA = env['whatsapp.message'].sudo()
        n = 0
        for p in partners:
            digits = re.sub(r'\D', '', p.mobile or p.phone or '')[-8:]
            if len(digits) < 8:
                continue
            msg = WA.search([('message_type', '=', 'inbound'), ('mobile_number', 'ilike', digits)],
                            order='create_date asc', limit=1)
            if not msg:
                continue
            body = re.sub(r'<[^>]+>', ' ', msg.body or '')
            if p.agent_capture_origin(body, first_message=True, when=msg.create_date):
                n += 1
        _logger.info("✅ MIGRATION 1.52.0: origen captado para %s de %s contactos", n, len(partners))
    except Exception as e:
        _logger.warning("MIGRATION 1.52.0: no pude captar orígenes: %s", e)

    # Primera corrida del motor (en seco): etapas + acciones que tocarían.
    try:
        res = env['cristal.agent.lifecycle'].cron_lifecycle_daily()
        _logger.info("✅ MIGRATION 1.52.0: ciclo de vida inicial %s", res)
    except Exception as e:
        _logger.warning("MIGRATION 1.52.0: no pude correr el ciclo de vida: %s", e)
