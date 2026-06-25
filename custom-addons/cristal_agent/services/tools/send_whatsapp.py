# -*- coding: utf-8 -*-
"""
Tool: send_whatsapp

Envía un mensaje WhatsApp al cliente AL TOQUE (sin esperar el cron).
Usa el método _send_message() del módulo whatsapp de Odoo, que dispara
la entrega inmediata vía la API de WhatsApp Business.

Patrón:
1. Crea un mail.message en el canal del cliente (model='discuss.channel', res_id=channel_id)
2. Crea un whatsapp.message vinculado, con state='outgoing'
3. Llama a _send_message() para envío inmediato

Si el método _send_message no existe (módulo whatsapp viejo o sin esa función),
queda en cola del cron.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class SendWhatsApp(AgentTool):
    name = "send_whatsapp"
    description = (
        "Envía un mensaje WhatsApp al cliente al toque, O postea en el canal interno con Joaco. "
        "Lo recibe casi instantáneamente. "
        "El body acepta HTML (<p>, <b>, <i>, <br>, listas). "
        "PUEDE adjuntar archivos: pasale attachment_ids (lista de IDs de ir.attachment). "
        "Para mandar PDF de cotización: primero llamá a generate_quote_pdf que devuelve attachment_id, "
        "después llamá a send_whatsapp con ese attachment_id en la lista. Mismo para lista de precios "
        "con generate_pricelist_pdf. "
        "USO 1 — Mensaje a cliente WA externo: pasá channel_id, body, wa_account_id "
        "(USÁ SIEMPRE LA MISMA con la que entró el mensaje del cliente: 3=Info, 5=Compras, 8=Crilimp), "
        "y mobile_number (con + adelante). "
        "USO 2 — Mensaje al canal interno Joaco↔Claudio: pasá channel_id del canal interno (típicamente 969) "
        "y body. NO necesitás wa_account_id ni mobile_number — el módulo detecta que es interno."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "channel_id": {
                "type": "integer",
                "description": "ID del discuss.channel del cliente (es el res_id del mail.message original).",
            },
            "body": {
                "type": "string",
                "description": "Texto del mensaje en HTML. Usá <p>...</p> para párrafos, "
                               "<br> para saltos. NO emojis raros, sí los normales 😊.",
            },
            "wa_account_id": {
                "type": "integer",
                "description": "ID de la cuenta de WhatsApp Business desde la que se envía. "
                               "Tipicamente: 3 (Info), 5 (Compras), 8 (Crilimp). "
                               "Usá la misma con la que entró el mensaje del cliente. "
                               "OMITIR si channel_id es el canal interno con Joaco.",
            },
            "mobile_number": {
                "type": "string",
                "description": "Número del cliente con + adelante (ej: '+5493585481191'). "
                               "Lo obtenés del campo mobile_number_formatted del whatsapp.message original "
                               "anteponiéndole '+'. OMITIR si es canal interno.",
            },
            "attachment_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "(Opcional) Lista de IDs de ir.attachment a adjuntar al mensaje. "
                               "Para mandar PDFs (cotizaciones, listas de precios) primero generalos "
                               "con generate_quote_pdf o generate_pricelist_pdf y pasá el attachment_id "
                               "que devuelven en esta lista.",
            },
        },
        "required": ["channel_id", "body"],
    }

    def _execute(self, env, run=None, channel_id=None, body=None,
                 wa_account_id=None, mobile_number=None, attachment_ids=None, **kwargs):
        if not (channel_id and body):
            return {"error": "Faltan parámetros obligatorios (channel_id, body)"}

        config = env['cristal.agent.config'].sudo().get_active()
        bot_partner = config.bot_partner_id
        if not bot_partner:
            # Fallback a OdooBot (partner de sistema, id 2)
            bot_partner = env['res.partner'].sudo().browse(2)
            if not bot_partner.exists():
                return {"error": "No se pudo determinar el partner del bot. Configurá bot_partner_id."}

        # Detectar si es el canal interno (chat con Joaco) — en ese caso NO necesita wa_account
        internal_channel = config.internal_channel_id
        is_internal_channel = bool(internal_channel and internal_channel.id == int(channel_id))

        if not is_internal_channel and not (wa_account_id and mobile_number):
            return {"error": "Para enviar a un cliente WA externo, wa_account_id y mobile_number son obligatorios"}

        # ═════════ CHECK VENTANA 24HS (solo para clientes externos) ═════════
        # Fix 1.10.5: si este run lo disparó un mensaje ENTRANTE del cliente
        # (trigger='whatsapp_message'), la ventana de 24hs está abierta POR
        # DEFINICIÓN — el cliente acaba de escribir. El chequeo de ventana
        # miraba el último inbound y a veces rebotaba con WINDOW_CLOSED contra
        # ese mismo inbound recién entrado (timing/índice), bloqueando la
        # respuesta. Caso real: Silvia Bazán (partner 80526), run 1269.
        # Saltamos el check solo en ese caso; los envíos proactivos del cron
        # (otros triggers) lo siguen respetando.
        skip_window_check = bool(run and getattr(run, 'trigger', None) == 'whatsapp_message')
        if not is_internal_channel and not skip_window_check:
            from ..helpers import is_24h_window_open, hours_since_last_inbound
            # v1.10.1 FIX: el partner para el chequeo de ventana es el que
            # disparó este run (el remitente REAL), no un miembro adivinado del
            # canal. Antes se tomaba others[0] de channel_partner_ids excluyendo
            # solo bot+owner; si había un operador interno (Guillermo, etc.) en
            # el canal, el chequeo miraba SU historial (sin inbound reciente) y
            # devolvía WINDOW_CLOSED falso aunque el cliente acabara de escribir.
            partner_check = None
            if run and run.partner_id:
                partner_check = run.partner_id
            else:
                try:
                    Channel = env['discuss.channel'].sudo()
                    ch = Channel.browse(int(channel_id))
                    if ch.exists() and ch.channel_partner_ids:
                        internal_ids = set(env['cristal.agent.config'].INTERNAL_PARTNER_IDS)
                        bot_pid = config.bot_partner_id.id if config.bot_partner_id else 2
                        owner_pid = config.owner_partner_id.id if config.owner_partner_id else 65374
                        internal_ids |= {bot_pid, owner_pid}
                        others = ch.channel_partner_ids.filtered(
                            lambda p: p.id not in internal_ids
                        )
                        if others:
                            partner_check = others[0]
                except Exception:
                    pass

            if partner_check:
                is_open, last_inbound = is_24h_window_open(
                    env, partner_check, wa_account_id=wa_account_id
                )
                if not is_open:
                    hours = hours_since_last_inbound(env, partner_check, wa_account_id) or 999
                    _logger.warning(
                        "Ventana 24hs CERRADA para %s (último inbound: %s, %s hs atrás)",
                        partner_check.name, last_inbound, int(hours)
                    )
                    return {
                        "error": "WINDOW_CLOSED",
                        "message": (
                            f"La ventana de 24hs de WhatsApp está CERRADA para {partner_check.name}. "
                            f"El cliente no escribió en las últimas 24hs "
                            f"(último inbound: {int(hours)}hs atrás). "
                            f"NO PUEDO mandar texto libre. "
                            f"Usá `send_whatsapp_template` con un template aprobado, "
                            f"o si no hay template apropiado, escalá a Joaco."
                        ),
                        "partner_id": partner_check.id,
                        "partner_name": partner_check.name,
                        "hours_since_last_inbound": int(hours),
                        "suggestion": "send_whatsapp_template",
                    }
        # ════════════════════════════════════════════════════════════════════

        # Asegurar HTML básico
        if not body.startswith('<'):
            body_html = f"<p>{body}</p>"
        else:
            body_html = body

        # Resolver subtype
        try:
            subtype_id = env.ref('mail.mt_comment').id
        except Exception:
            subtype_id = 1  # fallback

        # Validar canal existe
        Channel = env['discuss.channel'].sudo()
        channel = Channel.browse(int(channel_id))
        if not channel.exists():
            return {"error": f"discuss.channel id={channel_id} no existe"}

        # Validar attachments si vienen
        attachments = env['ir.attachment']
        if attachment_ids:
            try:
                ids_clean = [int(a) for a in attachment_ids if a]
                attachments = env['ir.attachment'].sudo().browse(ids_clean).exists()
                if len(attachments) != len(ids_clean):
                    _logger.warning(
                        "Algunos attachment_ids no existen. Pedidos: %s, encontrados: %s",
                        ids_clean, attachments.ids
                    )
            except Exception as e:
                return {"error": f"attachment_ids inválidos: {e}"}

        # Paso 1: crear mail.message (siempre)
        # Usamos contexto from_cristal_agent para que el hook de mail_message
        # no nos active el takeover (porque somos nosotros el "humano" desde su perspectiva)
        MailMsg = env['mail.message'].sudo().with_context(from_cristal_agent=True)
        mail_vals = {
            'author_id': bot_partner.id,
            'body': body_html,
            'message_type': 'comment' if is_internal_channel else 'whatsapp_message',
            'model': 'discuss.channel',
            'res_id': channel.id,
            'subtype_id': subtype_id,
        }
        if attachments:
            mail_vals['attachment_ids'] = [(4, a.id) for a in attachments]
        try:
            mail_msg = MailMsg.create(mail_vals)
        except Exception as e:
            _logger.exception("Error creando mail.message: %s", e)
            return {"error": f"No se pudo crear el mail.message: {e}"}

        # Si es canal interno, terminamos acá (no se crea whatsapp.message ni se envía)
        if is_internal_channel:
            _logger.info("📝 Mensaje posteado en canal interno %s", channel.name)
            return {
                "ok": True,
                "mail_message_id": mail_msg.id,
                "is_internal": True,
                "attachments_count": len(attachments),
                "summary": f"Mensaje posteado en canal interno {channel.name}",
            }

        # Paso 2 (solo para WA externo): crear whatsapp.message
        WhatsApp = env['whatsapp.message'].sudo()
        wa_vals = {
            'mail_message_id': mail_msg.id,
            'wa_account_id': wa_account_id,
            'mobile_number': mobile_number,
            'message_type': 'outbound',
            'state': 'outgoing',
        }
        # En Odoo 18 el módulo whatsapp soporta attachment a través de mail_message_id.attachment_ids
        # (ya seteados arriba). Algunas versiones también tienen un campo directo 'attachment_ids'
        # en whatsapp.message — lo intentamos con fallback.
        if attachments and hasattr(WhatsApp, '_fields') and 'attachment_ids' in WhatsApp._fields:
            wa_vals['attachment_ids'] = [(4, a.id) for a in attachments]
        try:
            wa_msg = WhatsApp.create(wa_vals)
        except Exception as e:
            _logger.exception("Error creando whatsapp.message: %s", e)
            return {"error": f"No se pudo crear el whatsapp.message: {e}"}

        # Paso 3: envío inmediato si el método existe (de chatbot_whatsapp viejo)
        sent_immediately = False
        try:
            if hasattr(wa_msg, '_send_message'):
                wa_msg._send_message()
                sent_immediately = True
                _logger.info("📤 Mensaje WA enviado al toque a %s con %d adjuntos",
                             mobile_number, len(attachments))
            else:
                _logger.info("📤 Mensaje WA encolado (cron) para %s", mobile_number)
        except Exception as e:
            _logger.warning("Error en _send_message(), queda en cola: %s", e)

        # Actualizar memory: incrementar contador y last_outbound
        if run and run.partner_id:
            try:
                from odoo import fields as odoo_fields
                Memory = env['cristal.agent.memory'].sudo()
                memory = Memory.search([('partner_id', '=', run.partner_id.id)], limit=1)
                if memory:
                    memory.increment_sent()
                run.partner_id.sudo().write({
                    'agent_last_outbound_at': odoo_fields.Datetime.now(),
                })
            except Exception as e:
                _logger.debug("No se pudo actualizar memory/partner: %s", e)

        return {
            "ok": True,
            "mail_message_id": mail_msg.id,
            "whatsapp_message_id": wa_msg.id,
            "sent_immediately": sent_immediately,
            "summary": f"Mensaje enviado a {mobile_number} ({'al toque' if sent_immediately else 'en cola'})",
        }
