# -*- coding: utf-8 -*-
"""
Controles determinísticos al ENVIAR un WhatsApp al cliente (v1.36).

Con Haiku, las reglas que solo están en el prompt se cumplen a medias. Estos
controles corren en send_whatsapp justo antes de mandar y cubren los errores que
Joaco vio en las conversaciones del 9 al 13/10/2026:

- 20% de primera compra ofrecido a clientes de la ruta / fuera de zona.
- "Joaquín te coordina el envío" y promesas de día/horario de entrega en Río Cuarto.
- "Te aviso en un minuto" un viernes a la tarde o un domingo.
- "Hoy estamos abiertos" un feriado.
- Textos largos a un cliente que ya dijo dos veces que no entiende o pidió audio.
- Mensajes duplicados (mismo texto dos veces en segundos) y adjuntos inventados.

Cada control, la PRIMERA vez que salta en una corrida, NO manda el mensaje y le
devuelve al bot la instrucción para corregirlo. Si en la misma corrida vuelve a
saltar, se aplica la corrección determinística (sacar la oración o recortar) y el
mensaje sale, para no dejar al cliente sin respuesta ni entrar en un loop.
"""
import json
import logging
import re
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+|<br\s*/?>|</p>\s*<p>', re.IGNORECASE)

# Promesas de envío que no podemos cumplir.
_RE_COORDINA_ENVIO = re.compile(
    r'(joaqu[ií]n|joaco)[^.!?<]{0,40}coordin\w*|coordin\w*[^.!?<]{0,25}env[ií]o'
    r'|env[ií]o[^.!?<]{0,25}coordin\w*',
    re.IGNORECASE)
# "En un minuto / ya te aviso / enseguida te confirmo".
_RE_MINUTOS = re.compile(
    r'\b(?:en|dentro de)\s+(?:un|unos|1|2|5|10|pocos|un par de)\s*(?:minut\w*|ratit\w*|rato)\b'
    r'|\bya te (?:aviso|confirmo|respondo|digo)\b|\benseguida te (?:aviso|confirmo|paso|digo)\b'
    r'|\bya le (?:aviso|confirmo|respondo)\b|\benseguida le (?:aviso|confirmo|paso)\b',
    re.IGNORECASE)
# Día/horario de ENTREGA comprometido (Río Cuarto).
_RE_ENTREGA_FECHA = re.compile(
    r'(?:\bentrega(?:mos|rlo|rle|ría)?\b|\brepart\w*|\bdespach\w*|\b(?:te|se) lo (?:llev|envi|mand)\w*'
    r'|\blo (?:llevamos|enviamos|mandamos)\b|\benviamos\b|\bllevamos\b|\bsale el pedido\b)'
    r'[^.!?<]{0,45}'
    r'\b(?:hoy|mañana|pasado mañana|lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|'
    r'\d{1,2}/\d{1,2}|a las \d{1,2})',
    re.IGNORECASE)
# "Hoy estamos abiertos / atendemos hasta las ..." (para días cerrados).
_RE_ABIERTO_HOY = re.compile(
    r'\b(?:hoy|ahora)\b[^.!?<]{0,35}\b(?:abiert\w*|atendemos|estamos hasta|te esperamos)',
    re.IGNORECASE)
# Señales de que el cliente no entiende o pide otro canal.
_RE_NO_ENTIENDE = re.compile(
    r'no (?:te |le )?entiendo|no entend[ií]|no comprendo|no me queda claro|no s[eé] c[oó]mo',
    re.IGNORECASE)
_RE_PIDE_AUDIO = re.compile(
    r'\baudio\b|\bll[aá]m(?:ame|eme|enme|ar|ada|ado|en)\b|\bme pod[eé]s llamar|\bme llam[aá]s',
    re.IGNORECASE)
CONFUSED_MAX_CHARS = 240


def _plain(body_html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', body_html or '')).strip()


def _strip_sentences(body_html, regex):
    """Saca las oraciones que matchean (último recurso)."""
    parts = re.split(r'(?<=[.!?])\s+', body_html or '')
    kept = [p for p in parts if not regex.search(re.sub(r'<[^>]+>', ' ', p))]
    out = ' '.join(kept).strip()
    return out.replace('<p></p>', '').replace('<p> </p>', '') or body_html


def _prior_guards(run):
    """Controles que ya saltaron en esta corrida."""
    seen = set()
    if not run:
        return seen
    try:
        for c in json.loads(run.tool_calls_log or '[]'):
            out = c.get('output') or {}
            if c.get('tool_name') == 'send_whatsapp' and isinstance(out, dict) \
                    and out.get('guard'):
                seen.add(out['guard'])
    except Exception:
        pass
    return seen


def confusion_signal(env, channel_id, hours=24):
    """(veces que dijo 'no entiendo' en las últimas horas, pidió audio/llamada en el
    último mensaje). Mira solo mensajes ENTRANTES del canal del cliente."""
    try:
        msgs = env['whatsapp.message'].sudo().search([
            ('mail_message_id.model', '=', 'discuss.channel'),
            ('mail_message_id.res_id', '=', int(channel_id)),
            ('message_type', '=', 'inbound'),
            ('create_date', '>=', datetime.now() - timedelta(hours=hours)),
        ], order='id desc', limit=20)
    except Exception:
        return 0, False
    texts = [_plain(m.mail_message_id.body or m.body or '') for m in msgs]
    count = sum(1 for t in texts if _RE_NO_ENTIENDE.search(t))
    wants_call = bool(texts and _RE_PIDE_AUDIO.search(texts[0]))
    return count, wants_call


def _known_attachment_ids(env, run):
    """Adjuntos que el bot puede mandar: los que devolvieron las tools (en esta
    corrida o en las del mismo cliente de las últimas 24 h) + el reporte
    institucional configurado."""
    ids = set()
    runs = run
    if run and run.partner_id:
        runs |= env['cristal.agent.run'].sudo().search([
            ('partner_id', '=', run.partner_id.id),
            ('create_date', '>=', datetime.now() - timedelta(hours=24)),
        ], limit=20)
    for r in runs or []:
        try:
            for c in json.loads(r.tool_calls_log or '[]'):
                out = c.get('output') or {}
                if isinstance(out, dict):
                    for key in ('attachment_id', 'pdf_attachment_id'):
                        if out.get(key):
                            ids.add(int(out[key]))
                    for a in out.get('attachment_ids') or []:
                        ids.add(int(a))
        except Exception:
            continue
    config = env['cristal.agent.config'].sudo().get_active()
    if config and config.institutional_report_attachment_id:
        ids.add(config.institutional_report_attachment_id.id)
    return ids


def check_attachments(env, run, attachment_ids):
    """None si los adjuntos son válidos; si no, el error para el bot.
    Caso real (canal 2997): el bot adjuntó el id 1 (inventado), el mensaje salió y
    después lo repitió con el PDF correcto → el cliente recibió el texto dos veces."""
    if not attachment_ids:
        return None
    try:
        wanted = [int(a) for a in attachment_ids if a]
    except Exception:
        wanted = []
    known = _known_attachment_ids(env, run)
    Att = env['ir.attachment'].sudo()
    bad = []
    for aid in wanted:
        att = Att.browse(aid).exists()
        if not att:
            bad.append(aid)
            continue
        if aid in known:
            continue
        # Adjuntos de una cotización del mismo cliente: también valen.
        if att.res_model == 'sale.order' and run and run.partner_id:
            order = env['sale.order'].sudo().browse(att.res_id).exists()
            if order and order.partner_id.commercial_partner_id == \
                    run.partner_id.commercial_partner_id:
                continue
        bad.append(aid)
    if not bad:
        return None
    return {
        "error": (f"NO MANDÉ EL MENSAJE: el adjunto {bad} no es válido (no lo generó "
                  f"ninguna herramienta en esta conversación). Usá EXACTAMENTE el "
                  f"attachment_id que devolvió generate_pricelist_pdf / "
                  f"generate_quote_pdf y mandá el mensaje UNA sola vez."),
        "guard": "attachment",
    }


def duplicate_recent(env, channel_id, body_html, bot_partner_id, seconds=300):
    """True si el bot ya mandó este mismo texto a este canal hace menos de `seconds`."""
    plain = _plain(body_html)
    if not plain:
        return False
    recent = env['mail.message'].sudo().search([
        ('model', '=', 'discuss.channel'),
        ('res_id', '=', int(channel_id)),
        ('author_id', '=', bot_partner_id),
        ('create_date', '>=', datetime.now() - timedelta(seconds=seconds)),
    ], order='id desc', limit=5)
    return any(_plain(m.body) == plain for m in recent)


def apply_send_guards(env, run, channel_id, body_html, partner=None):
    """Devuelve (body_html, error_dict|None). Solo para canales de clientes."""
    from .helpers import (first_purchase_discount_status, mentions_first_purchase_discount,
                          strip_first_purchase_offer, business_status)
    prior = _prior_guards(run)
    partner = partner or (run.partner_id if run else None)
    plain = _plain(body_html)

    def block(guard, instruction, fixed_body):
        if guard in prior:
            _logger.info("🛡️ Control '%s' (2da vez): corrijo y mando.", guard)
            return fixed_body, None
        _logger.info("🛡️ Control '%s': mensaje NO enviado, le pido al bot que corrija.", guard)
        return body_html, {"error": instruction, "guard": guard}

    # 1) 20% de primera compra: SOLO Río Cuarto / Las Higueras.
    if partner and mentions_first_purchase_discount(body_html):
        status, reason = first_purchase_discount_status(env, partner)
        if status != 'allowed':
            return block(
                'first_purchase_zone',
                f"NO MANDÉ EL MENSAJE: menciona el 20% y a este cliente NO le corresponde "
                f"({reason}). El 20% de primera compra es SOLO para Río Cuarto / Las "
                f"Higueras. Volvé a mandarlo SIN el 20% (la promo Ariel/Skip $600/L desde "
                f"100 L sí vale).",
                strip_first_purchase_offer(body_html))

    # 2) "Joaquín te coordina el envío" — prohibido.
    if _RE_COORDINA_ENVIO.search(plain):
        return block(
            'coordina_envio',
            "NO MANDÉ EL MENSAJE: no se promete que Joaquín (ni nadie) coordina el envío. "
            "Si es de fuera de zona, ofrecé retiro en planta (San Martín 2350, Río Cuarto) "
            "o transporte a cargo del cliente, y escalá a Joaco UNA vez.",
            _strip_sentences(body_html, _RE_COORDINA_ENVIO))

    st = business_status(env)
    # 3) Promesas de minutos ("te aviso en un minuto").
    if _RE_MINUTOS.search(plain):
        return block(
            'promesa_minutos',
            f"NO MANDÉ EL MENSAJE: no prometas minutos ('en un minuto', 'ya te aviso'). "
            f"Decí: 'Lo consulto y le confirmo {st['confirm_when']}'.",
            _strip_sentences(body_html, _RE_MINUTOS))

    # 4) Hoy cerrado (feriado/domingo) y dice que estamos abiertos.
    if st['closed_today'] and _RE_ABIERTO_HOY.search(plain):
        return block(
            'abierto_dia_cerrado',
            f"NO MANDÉ EL MENSAJE: HOY NO atendemos ({st['closed_today']}). Decile que hoy "
            f"no atendemos y que le respondemos/confirmamos {st['confirm_when']}. No "
            f"confirmes retiros ni entregas para hoy.",
            _strip_sentences(body_html, _RE_ABIERTO_HOY))

    # 5) Río Cuarto: nunca un día/horario de entrega comprometido.
    if partner and _RE_ENTREGA_FECHA.search(plain):
        status, _r = first_purchase_discount_status(env, partner)  # allowed = Río Cuarto
        if status == 'allowed':
            return block(
                'entrega_rc',
                "NO MANDÉ EL MENSAJE: para Río Cuarto NO se compromete día ni horario de "
                "entrega. Decí 'le confirmamos el día de entrega' y escalá el pedido a Joaco.",
                _strip_sentences(body_html, _RE_ENTREGA_FECHA))

    # 6) Cliente que no entiende / pide audio o llamada: mensaje corto + escalar.
    count, wants_call = confusion_signal(env, channel_id)
    if (count >= 2 or wants_call) and len(plain) > CONFUSED_MAX_CHARS:
        first = re.split(r'(?<=[.!?])\s+', plain)[0][:CONFUSED_MAX_CHARS]
        return block(
            'cliente_no_entiende',
            "NO MANDÉ EL MENSAJE: el cliente dijo que no entiende (o pidió audio/llamada). "
            "Mandale UN mensaje corto, de UNA sola idea (máx. 2 líneas), por ejemplo: "
            "'Le pido a Joaquín que lo llame y se lo explica.' y escalá a Joaco con "
            "escalate_to_joaco para que lo llame.",
            f"<p>{first}</p>")

    return body_html, None
