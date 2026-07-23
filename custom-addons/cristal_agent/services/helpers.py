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
