# -*- coding: utf-8 -*-
"""v1.57 — Encuesta post-compra, reenganche de ruta y ritual Oro: Claudio necesita
saber cómo seguir una respuesta a la encuesta (la manda el motor, sin él)."""
import logging
from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

KB = [
    ("Encuesta post-compra: cómo seguirla", 'regla_negocio',
     "El sistema manda solo una encuesta de satisfacción (plantilla con botones Bien / "
     "Regular / Mal) entre 7 y 14 días después de un pedido. Si el cliente contesta con un "
     "botón o un texto corto: la respuesta ya queda registrada en su ficha. Si dijo BIEN: agradecé "
     "en una línea y, solo si en la base de conocimiento hay un link de reseñas de Google, pedile una reseña (nunca inventes el link). Si dijo REGULAR o MAL: preguntá qué pasó (producto, entrega, precio, "
     "atención), guardalo con update_observation y escalá a Joaco con escalate_to_joaco "
     "resumiendo el problema. No ofrezcas descuentos por una queja: eso lo decide Joaco."),
    ("Ritual mensual nivel ORO", 'politica_comercial',
     "La primera semana de cada mes el motor te agenda un saludo a cada cliente ORO. Es un "
     "mensaje de reconocimiento, no una oferta: gracias por el mes, su descuento ORO se "
     "aplica solo en cada cotización, y preguntás si necesita algo para arrancar el mes. "
     "Si le toca reponer, ofrecé reponer lo que llevó. Un mensaje, corto."),
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Know = env['cristal.agent.knowledge'].sudo()
    for name, cat, content in KB:
        if Know.with_context(active_test=False).search_count([('name', '=', name)]):
            continue
        Know.create({'name': name, 'category': cat, 'content': content, 'applies_to': 'all',
                     'client_type_filter': 'mayorista', 'source': 'default', 'active': True})
        _logger.info("v1.57: knowledge «%s» creada", name)
