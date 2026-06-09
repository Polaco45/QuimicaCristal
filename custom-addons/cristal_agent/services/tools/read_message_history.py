# -*- coding: utf-8 -*-
"""
Tool: read_message_history

Lee los últimos N mensajes del canal del cliente (entrantes y salientes).
Crítico para que Claude tenga contexto de la conversación.
"""
import logging
import re
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

HTML_TAGS = re.compile(r"<[^>]+>")


def _clean(text):
    if not text:
        return ""
    return re.sub(HTML_TAGS, "", text).strip()


@ToolRegistry.register
class ReadMessageHistory(AgentTool):
    name = "read_message_history"
    description = (
        "Lee los últimos mensajes de un canal de WhatsApp (mail.message en un discuss.channel). "
        "Te da el contexto completo de la conversación con el cliente. "
        "Por defecto trae 10 mensajes; podés pedir más si hace falta. "
        "Cada mensaje incluye: id, autor, fecha, tipo (entrante/saliente), y texto limpio."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "channel_id": {
                "type": "integer",
                "description": "ID del discuss.channel del cliente.",
            },
            "limit": {
                "type": "integer",
                "description": "Cantidad de mensajes a traer (default 10, máx 30).",
                "default": 10,
            },
        },
        "required": ["channel_id"],
    }

    def _execute(self, env, run=None, channel_id=None, limit=10, **kwargs):
        if not channel_id:
            return {"error": "channel_id es obligatorio"}

        limit = max(1, min(30, int(limit or 10)))

        Channel = env['discuss.channel'].sudo()
        channel = Channel.browse(channel_id)
        if not channel.exists():
            return {"error": f"discuss.channel id={channel_id} no existe"}

        Msg = env['mail.message'].sudo()
        messages = Msg.search([
            ('model', '=', 'discuss.channel'),
            ('res_id', '=', channel.id),
        ], order='date desc', limit=limit)

        # Identificar el partner del canal para clasificar entrantes/salientes
        config = env['cristal.agent.config'].sudo().get_active()
        bot_partner_id = config.bot_partner_id.id if config.bot_partner_id else 80799

        result = []
        for m in messages:
            author = m.author_id
            is_bot = (author.id == bot_partner_id) if author else False
            is_internal_user = bool(author and author.user_ids) if author else False

            direction = 'unknown'
            if is_bot:
                direction = 'outbound_bot'
            elif is_internal_user:
                direction = 'outbound_human'  # Joaco u otro empleado
            else:
                direction = 'inbound'  # cliente

            result.append({
                'id': m.id,
                'date': str(m.date) if m.date else '',
                'author_name': author.name if author else '(sin autor)',
                'author_id': author.id if author else 0,
                'direction': direction,
                'message_type': m.message_type,
                'body': _clean(m.body or '')[:600],  # Limitar largo por mensaje
            })

        # Devolvemos en orden cronológico (oldest first) para que sea más fácil de leer
        result.reverse()

        return {
            "ok": True,
            "channel_id": channel_id,
            "channel_name": channel.name,
            "count": len(result),
            "messages": result,
        }
