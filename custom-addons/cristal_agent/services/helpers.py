# -*- coding: utf-8 -*-
"""
Helpers compartidos por las tools y servicios.
"""
import re
from datetime import datetime, timedelta


# ─────────────────────────── Sanitizador de tono ───────────────────────────
# El prompt prohíbe explícitamente las muletillas de festejo ("Perfecto",
# "Excelente", etc.), pero Haiku igual las usa como apertura en ~1 de cada 7
# mensajes. Este filtro determinístico las saca del texto SALIENTE al cliente,
# sin costo de tokens y de forma garantizada. Solo toca la palabra cuando se usa
# como muletilla de apertura (inicio de párrafo, después de un saludo, o
# "Dale, perfecto"); NUNCA cuando "excelente" es un adjetivo real en medio de
# una frase (ej: "es excelente para la ropa"), porque en ese caso no arranca
# párrafo ni sigue a un saludo.
_TONE_OPENERS = (
    r'(?:perfecto|perfectos|perfecta|excelente|excelentes|geniales|genial|'
    r'buen[ií]simo|buen[ií]sima|b[áa]rbaro|b[áa]rbara|incre[íi]ble|'
    r'qu[eé]\s+bueno|qu[eé]\s+grande|me\s+encanta|espectacular)'
)
# "Dale, perfecto" / "dale perfecto" → "Dale"
_RE_DALE_OPENER = re.compile(r'\bdale[,\s]+' + _TONE_OPENERS + r'\b', re.IGNORECASE)
# Muletilla después de un saludo: "Hola Sandra, perfecto." → "Hola Sandra."
_RE_AFTER_GREETING = re.compile(
    r'(hola[^,<.]{0,30}?),\s*¡?\s*' + _TONE_OPENERS + r'\s*!*[.,]?',
    re.IGNORECASE)
# Muletilla al inicio del mensaje o de un párrafo (tras '>' de <p>/<br> o inicio):
# "Perfecto Sandra. ..." / "<p>Genial, te armo..." → saca la muletilla y deja
# la primera letra siguiente en mayúscula.
_RE_OPENER_START = re.compile(
    r'(^|>)\s*¡?\s*' + _TONE_OPENERS + r'\s*!*[.,]?\s*(\w)?',
    re.IGNORECASE)
# Muletilla al inicio de una ORACIÓN (después de . ! ?): "Soy Claudio de Química
# Cristal. Perfecto, te doy los precios" → "... Cristal. Te doy los precios".
# Exige puntuación después de la palabra (forma de muletilla), para no tocar un
# adjetivo real que arranca oración ("Excelente calidad la de este jabón").
_RE_OPENER_SENTENCE = re.compile(
    r'([.!?]\s+)¡?\s*' + _TONE_OPENERS + r'\s*!*[,.!]\s*(\w)?',
    re.IGNORECASE)
# Muletilla después de un guión largo: "Veo que tiene una despensa — perfecto, te
# atendemos" → "Veo que tiene una despensa — te atendemos". Misma exigencia de
# puntuación que arriba; la letra siguiente queda como estaba.
_RE_OPENER_DASH = re.compile(
    r'(\s[—–]\s*)¡?\s*' + _TONE_OPENERS + r'\s*!*[,.!]\s*',
    re.IGNORECASE)


def _cap_after_start(m):
    nxt = m.group(2) or ''
    return m.group(1) + nxt.upper()


def sanitize_tone(body_html):
    """Saca las muletillas de festejo prohibidas del texto saliente al cliente.

    Es idempotente y conservador: solo actúa sobre muletillas de apertura, no
    sobre adjetivos legítimos en medio de la frase. Devuelve el HTML limpio.
    """
    if not body_html:
        return body_html
    txt = _RE_DALE_OPENER.sub('Dale', body_html)
    txt = _RE_AFTER_GREETING.sub(r'\1.', txt)
    txt = _RE_OPENER_START.sub(_cap_after_start, txt)
    txt = _RE_OPENER_SENTENCE.sub(_cap_after_start, txt)
    txt = _RE_OPENER_DASH.sub(r'\1', txt)
    return txt


def is_24h_window_open(env, partner, wa_account_id=None):
    """
    Determina si la ventana de WhatsApp de 24hs está abierta para un cliente.

    La ventana está abierta si el cliente nos escribió un mensaje en las
    últimas 24hs. En ese caso podemos mandarle texto libre.

    Si está cerrada, solo podemos iniciar con templates aprobados por Meta.

    Args:
        env: Odoo env
        partner: res.partner del cliente
        wa_account_id: (opcional) limitar a una cuenta específica

    Returns:
        (bool, datetime or None): (ventana_abierta, fecha_ultimo_inbound)
    """
    if not partner or not partner.exists():
        return False, None

    threshold = datetime.now() - timedelta(hours=24)
    WhatsApp = env['whatsapp.message'].sudo()

    # Buscar el último mensaje inbound del cliente
    domain = [
        ('mobile_number', 'in', [
            partner.mobile or '',
            partner.phone or '',
            '+' + (partner.mobile or '').lstrip('+').lstrip('0').lstrip(),
            '+' + (partner.phone or '').lstrip('+').lstrip('0').lstrip(),
        ]),
        ('message_type', '=', 'inbound'),
    ]
    if wa_account_id:
        domain.append(('wa_account_id', '=', wa_account_id))

    last_inbound = WhatsApp.search(domain, order='create_date desc', limit=1)
    if not last_inbound:
        return False, None

    is_open = last_inbound.create_date >= threshold
    return is_open, last_inbound.create_date


def hours_since_last_inbound(env, partner, wa_account_id=None):
    """Devuelve cuántas horas pasaron desde el último mensaje del cliente,
    o None si nunca escribió."""
    _, last_inbound_date = is_24h_window_open(env, partner, wa_account_id)
    if not last_inbound_date:
        return None
    delta = datetime.now() - last_inbound_date
    return delta.total_seconds() / 3600


# ─────────────────────── Fecha y hora de ARGENTINA (v1.33) ───────────────────────
# El servidor de Odoo.sh corre en UTC (3 h adelante). Todo lo que Claudio le dice
# al cliente ("hoy", "mañana", "martes") tiene que salir de la hora de Argentina,
# nunca de datetime.now() pelado. Bugs reales: "mañana martes" dicho un martes, y
# "tu pedido sale esta mañana" dicho a las 21:26.
DEFAULT_TZ = 'America/Argentina/Cordoba'
WEEKDAYS_ES = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']


def tz_ar(env):
    """Zona horaria del negocio (pytz), de la config."""
    import pytz
    config = env['cristal.agent.config'].sudo().get_active()
    return pytz.timezone(config.timezone if config and config.timezone else DEFAULT_TZ)


def now_ar(env):
    """Fecha y hora actual en la zona horaria del negocio (datetime con tz)."""
    return datetime.now(tz_ar(env))


def fmt_day(d):
    """date → 'miércoles 30/09'."""
    return f"{WEEKDAYS_ES[d.weekday()]} {d.strftime('%d/%m')}"


def date_context_ar(env, now=None):
    """Calendario listo para el prompt: hoy, mañana y pasado mañana con su día de
    la semana ya calculado (Haiku se equivoca si tiene que calcularlo solo)."""
    now = now or now_ar(env)
    d = now.date()
    return {
        'now': now,
        'hora': now.strftime('%H:%M'),
        'hoy': fmt_day(d) + d.strftime('/%Y'),
        'manana': fmt_day(d + timedelta(days=1)),
        'pasado': fmt_day(d + timedelta(days=2)),
    }


def within_contact_hours(env, now=None):
    """True si es horario para que Claudio INICIE mensajes (seguimientos,
    recordatorios, reintentos). A quien escribe primero se le contesta siempre.
    Ventana: config.work_hours_start..work_hours_end (hora Argentina), todos los días."""
    config = env['cristal.agent.config'].sudo().get_active()
    start = config.work_hours_start if config else 7.5
    end = config.work_hours_end if config else 21.5
    now = now or now_ar(env)
    hour = now.hour + now.minute / 60.0
    return start <= hour < end


def to_ar(env, dt):
    """Datetime naive en UTC (como lo guarda Odoo) → datetime con hora Argentina."""
    import pytz
    if not dt:
        return dt
    return pytz.utc.localize(dt).astimezone(tz_ar(env))


# ─────────────────────── Bidones: aviso garantizado (v1.33) ───────────────────────
# Joaco: "tiene que aclarar el tema de los bidones SIEMPRE" — hubo clientes que
# fueron a retirar sin saberlo. El prompt y las tools lo piden, pero el modelo a
# veces responde sin pasar por una tool. Este filtro determinístico (como el de
# tono) agrega la aclaración cuando el mensaje habla de granel y no la trae, salvo
# que Claudio ya la haya explicado en ese chat en las últimas 24 h.
_RE_GRANEL_QTY = re.compile(
    r'\b(?:20|40|60|80|100|120|140|160|180|200)\s*(?:l|lts?|litros?)\b', re.IGNORECASE)


def _strip_accents(txt):
    import unicodedata
    txt = unicodedata.normalize('NFKD', txt or '')
    return ''.join(c for c in txt if not unicodedata.combining(c))


def ensure_bidones_notice(env, channel_id, body_html):
    """Si el mensaje habla de granel y no menciona los bidones (y no se explicó en
    las últimas 24 h en ese chat), agrega un párrafo con la regla del recambio."""
    if not body_html:
        return body_html
    plain = _strip_accents(re.sub(r'<[^>]+>', ' ', body_html)).lower()
    talks_granel = 'granel' in plain or bool(_RE_GRANEL_QTY.search(plain))
    if not talks_granel or 'bidon' in plain:
        return body_html
    config = env['cristal.agent.config'].sudo().get_active()
    try:
        bot = config.bot_partner_id if config else False
        domain = [
            ('model', '=', 'discuss.channel'), ('res_id', '=', int(channel_id)),
            ('create_date', '>=', datetime.now() - timedelta(hours=24)),
            '|', ('body', 'ilike', 'bidón'), ('body', 'ilike', 'bidon'),
        ]
        if bot:
            domain.append(('author_id', '=', bot.id))
        if env['mail.message'].sudo().search_count(domain):
            return body_html
    except Exception:
        pass
    price = config.bidon_price if config else 3500.0
    price_txt = '${:,.0f}'.format(price).replace(',', '.')
    return body_html + (
        f"<p>Importante: el granel va en bidones de 20 L. Si trae sus bidones vacíos "
        f"para el recambio no se cobran; si no, cada bidón nuevo sale {price_txt}.</p>")
