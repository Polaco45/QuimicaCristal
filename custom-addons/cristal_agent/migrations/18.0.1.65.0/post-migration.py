# -*- coding: utf-8 -*-
"""Migración 18.0.1.65.0 — Conversión tanda 2 (10/11/2026).

- Punto 1: con la lista, si ya sabe el rubro, Claudio ofrece el combo que le corresponde.
- Punto 8: aprende los nombres que usan los clientes (add_knowledge / search_knowledge).
- Punto 11: entregas, faltantes y reclamos comunes van con derive_delivery_issue al
  responsable de entregas (Guillermo, user 15), no a Joaco.
- Regla de Joaco: solo lo de Fabricación se presenta como hecho por nosotros (lavandina y
  cloro son Fraccionado).
Reemplazos textuales e idempotentes sobre el prompt vivo; claudio_v10.md tiene los mismos.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

REPLACEMENTS = [
    ("**Productos:** fabricación propia de líquidos a granel (línea lavandería: jabón líquido, suavizante, quitamanchas; detergentes; desengrasantes; lavandina; cloro; ceras y mantenimiento de pisos; jabón de manos) **y** línea de distribución/secos",
     "**Productos:** fabricación propia de líquidos a granel (línea lavandería: jabón líquido, suavizante, quitamanchas; detergentes; desengrasantes; ceras y mantenimiento de pisos; jabón de manos), **fraccionado** (lavandina y cloro: los vendemos a granel, pero **no digas que los fabricamos**: \"hecho en nuestra fábrica\" va solo para lo de Fabricación) **y** línea de distribución/secos"),
    ("ofrecé lo más parecido que sí haya y escalá a Joaco **UNA sola vez** con todas las consultas juntas.",
     "ofrecé lo más parecido que sí haya y escalá a Joaco **UNA sola vez** con todas las consultas juntas. Antes de decir que no está, buscá también con `search_knowledge` (ahí quedan los nombres que usan los clientes). **Aprendé esos nombres:** si un cliente le dice a un producto con otro nombre (marca, apodo, \"el azul\") y descubrís cuál es, guardalo con `add_knowledge` (category='producto', name='Nombre que usan: X', content='Cuando un cliente pide X se refiere a [producto y código]') para no volver a preguntarlo ni escalarlo."),
    ("(nunca mandes el mismo texto dos veces: usá el `attachment_id` exacto que te devolvió la tool).",
     "(nunca mandes el mismo texto dos veces: usá el `attachment_id` exacto que te devolvió la tool). **Si ya sabés su rubro**, en ese mismo mensaje ofrecé en una línea el combo que le corresponde (el Combo Emprendedor para almacén, kiosco o quien arranca a revender; o el combo de su rubro si figura en el contexto)."),
    ("Escalá a Joaco SOLO en lo GRAVE o lo que está pautado**: reclamo serio,",
     "Escalá a Joaco SOLO en lo GRAVE o lo que está pautado**: reclamo serio (las consultas de entrega, faltantes y reclamos comunes de un pedido confirmado van con `derive_delivery_issue` al responsable de entregas, no a Joaco),"),
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
        _logger.info("MIGRATION 1.65.0: sin config activa")
        return
    if not config.delivery_issue_user_id:
        user = env['res.users'].browse(15).exists()
        if user and 'guillermo' in (user.name or '').lower():
            config.delivery_issue_user_id = user.id
    if config.system_prompt:
        text, done, missing = apply(config.system_prompt)
        if text != config.system_prompt:
            config.system_prompt = text
        _logger.info("✅ MIGRATION 1.65.0: prompt (%s) — %s reemplazos ok",
                     config.prompt_version, len(done))
        for m in missing:
            _logger.warning("⚠️ MIGRATION 1.65.0: no encontré en el prompt: %s…", m)
