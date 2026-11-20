# -*- coding: utf-8 -*-
"""1.81.0 — Retiros con hora del depósito + reglas de atención (Joaco, 20/11/2026).

- Parámetros del aviso al depósito (Guillermo): partner "Guille" (+54 9 351 677-4891) y su
  usuario; solo pedidos confirmados desde ahora.
- El usuario de Guillermo tenía el celular sin el 9: se corrige.
- Bloque de reglas al principio del prompt (caso Pablo Montero S07144 y revisión de 48 h).
"""
import logging

from odoo import api, fields, SUPERUSER_ID

_logger = logging.getLogger(__name__)

MARK = "REGLAS DE ATENCIÓN 20/11"
BLOCK = (
    "## ⚠️ " + MARK + " (Joaco — pisan cualquier otra indicación de este texto)\n"
    "- RETIRO POR TERCEROS: si el pedido está confirmado, lo puede retirar quien el cliente "
    "mande (comisionista, empleado, familiar) diciendo el número de pedido. NO hace falta "
    "autorización de Joaquín: decile \"perfecto, que pase con el número de pedido Sxxxx\".\n"
    "- PROHIBIDO decir \"lo consulto con Joaquín y le confirmo hoy\" o prometer una respuesta "
    "que no depende de vos. Si algo no lo podés resolver, decí concretamente qué va a pasar.\n"
    "- RETIRO: al confirmarlo decí que se prepara en el día y que el depósito le avisa por acá "
    "la hora en que queda listo. Si pregunta la hora y todavía no está, decile que apenas el "
    "depósito la confirme le llega el aviso.\n"
    "- COMPROBANTE DE PAGO: agradecé y decí que queda registrado. Un pedido confirmado NO se "
    "frena por eso: la entrega o el retiro siguen como estaban.\n"
    "- PRESUPUESTO Y BIDONES: si el cliente dice cuánto quiere gastar, la cotización no lo "
    "supera; si dice cuántos bidones vacíos tiene, los bidones nuevos son solo los que faltan.\n"
    "- Si el cliente ya dijo cuándo confirma (\"la semana que viene\", \"el 1/12\"), no le "
    "preguntes \"¿la confirma?\" antes de esa fecha.\n"
    "- Si el cliente suma algo a una cotización que todavía no confirmó, agregalo a ESA "
    "cotización; no armes otra.\n"
    "- No nombres una cotización con una salida del camión que ya pasó: primero actualizala a "
    "la próxima salida.\n"
    "- Tratá SIEMPRE de VOS (nunca \"usted\"), mensajes cortos y sin repetir lo que ya dijiste. "
    "A un \"ok\" o un sticker no le contestes lo mismo de nuevo.\n\n")

OLD_PICKUP = ("- Al confirmar un retiro: \"Lo preparamos en el día y te avisamos por WhatsApp cuando esté "
              "listo para retirar\" (no prometas hora exacta).")
NEW_PICKUP = ("- Al confirmar un retiro: \"Lo preparamos en el día; el depósito te confirma por acá "
              "la hora en que queda listo\" (no inventes la hora).")

KB_NAME = "Retiro por terceros y hora de retiro (20/11/2026)"
KB_CONTENT = (
    "RETIRO POR TERCEROS: un pedido confirmado lo puede retirar quien mande el cliente "
    "(comisionista, empleado) con el número de pedido; no hace falta autorización de Joaquín. "
    "HORA DE RETIRO: cuando se confirma un pedido para retirar, el depósito (Guillermo) dice a "
    "qué hora queda listo y al cliente le llega por WhatsApp \"Tu pedido Sxxxx va a estar listo "
    "hoy a las HH hs\"; cuando está armado le llega \"ya está listo para retirar\". Claudio no "
    "inventa la hora: si el cliente pregunta y todavía no llegó, le dice que el depósito se la "
    "confirma por acá. Horario: L-V 8 a 13 y 17 a 20, sábados 9 a 13.")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    ICP = env['ir.config_parameter'].sudo()
    Partner = env['res.partner'].sudo()
    staff = Partner.search([('mobile', '=', '+5493516774891')], limit=1)
    if not staff:
        staff = Partner.search([('mobile', 'ilike', '6774891'), ('name', 'ilike', 'guille')],
                               limit=1)
    if staff:
        ICP.set_param('cristal_agent.pickup_staff_partner_id', str(staff.id))
    user = env['res.users'].sudo().search([('login', '!=', False),
                                           ('partner_id.name', 'ilike', 'Guillermo')], limit=1)
    if user:
        ICP.set_param('cristal_agent.pickup_staff_user_id', str(user.id))
        if user.partner_id.mobile and '6774891' in user.partner_id.mobile \
                and not user.partner_id.mobile.startswith('+549'):
            user.partner_id.mobile = '+5493516774891'
    ICP.set_param('cristal_agent.pickup_staff_since', fields.Datetime.to_string(fields.Datetime.now()))
    if not ICP.get_param('cristal_agent.pickup_staff_enabled'):
        ICP.set_param('cristal_agent.pickup_staff_enabled', '1')

    config = env['cristal.agent.config'].search([('active', '=', True)], limit=1)
    if config and config.system_prompt:
        prompt = config.system_prompt
        if OLD_PICKUP in prompt:
            prompt = prompt.replace(OLD_PICKUP, NEW_PICKUP)
        if MARK not in prompt:
            prompt = BLOCK + prompt
        config.system_prompt = prompt

    KB = env['cristal.agent.knowledge'].with_context(active_test=False)
    kb = KB.search([('name', '=', KB_NAME)], limit=1)
    if not kb:
        ref = KB.search([('name', 'ilike', 'Retiro en el local con pedido previo')], limit=1)
        vals = {'name': KB_NAME, 'content': KB_CONTENT}
        if ref:
            # Mismos destinatarios y prioridad que la entrada de retiro con pedido previo.
            for f in ('applies_to', 'client_type_filter', 'priority', 'category'):
                if f in ref._fields:
                    vals[f] = ref[f]
        KB.create(vals)
    _logger.info("1.81.0: depósito=%s usuario=%s, prompt y conocimiento actualizados",
                 staff.id if staff else None, user.id if user else None)
