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
    # (?:[^\w\s¡]+\s*)? = un emoji opcional en el medio ("Cristal. 👋 Perfecto, ...")
    r'([.!?]\s+(?:[^\w\s¡]+\s*)?)¡?\s*' + _TONE_OPENERS + r'\s*!*[,.!]\s*(\w)?',
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


def rc_no_delivery_day(env):
    """Día sin reparto en Río Cuarto (sale el camión de la ruta), de la config.
    v1.35: la ruta pasó de jueves a miércoles; los textos salen de acá."""
    config = env['cristal.agent.config'].sudo().get_active()
    return WEEKDAYS_ES[int(config.rc_no_delivery_weekday) % 7] if config else 'miércoles'


def route_weekday(env):
    """Día de salida del camión (el de los circuitos activos)."""
    circuit = env['cristal.agent.circuit'].sudo().search([('active', '=', True)], limit=1)
    return WEEKDAYS_ES[int(circuit.weekday)] if circuit and circuit.weekday else 'miércoles'


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
        f"<p>Importante: el granel va en bidones de 20 L con recambio: por cada bidón "
        f"lleno se entrega uno vacío de 20 L con tapa (si se lo enviamos, al recibir el "
        f"pedido; si retira, en la planta). Si no tiene vacíos para canjear, cada bidón "
        f"nuevo sale {price_txt}.</p>")


# ─────────────────────── Control de precios al enviar (v1.34) ───────────────────────
# Caso real (02/10): el cliente pidió precios de jabones; search_products no trajo
# los jabones a granel y Claudio les puso "$720/L" (el precio del detergente).
# Antes de mandar, cada precio POR LITRO del mensaje tiene que corresponder a un
# producto que las tools devolvieron en esta corrida, con ese precio (o con un
# descuento válido: 20% 1ra compra, 5%/10% de nivel) o a un precio de una oferta
# vigente. Si no, el mensaje no sale y el bot tiene que buscar el producto.
_RE_PRICE_PER_L = re.compile(
    r'\$\s?(\d{1,3}(?:\.\d{3})*|\d+)(?:,\d+)?\s*'
    r'(?:/\s*(?:l|lt|lts|litro)\b|(?:x|por|el)\s+(?:litro|lt|l)\b)',
    re.IGNORECASE)
_GENERIC_NAME_WORDS = {
    'jabon', 'jabones', 'b', 'e', 'be', 'detergente', 'detergentes', 'liquido',
    'liquidos', 'a', 'granel', 'de', 'del', 'el', 'la', 'los', 'las', 'x', 'l', 'lt',
    'lts', 'litro', 'litros', 'para', 'ropa', 'y', 'c', 'con', 'en', 'por', 'precio',
    'mayorista', 'sale', 'esta', 'cuesta', 'vale',
}
_ALLOWED_FACTORS = (1.0, 0.8, 0.95, 0.9)


def _tokens(txt):
    plain = _strip_accents(txt or '').lower()
    return {w for w in re.findall(r'[a-z0-9]+', plain) if w not in _GENERIC_NAME_WORDS
            and not w.isdigit()}


def _known_prices_from_run(run):
    """[(tokens_del_nombre, precio)] de lo que devolvieron las tools en esta corrida
    y en las corridas del mismo cliente de las últimas 24 h (el cliente pregunta en
    un mensaje y confirma en el siguiente)."""
    import json
    known = []
    runs = run
    if run.partner_id:
        runs |= run.env['cristal.agent.run'].sudo().search([
            ('partner_id', '=', run.partner_id.id), ('id', '!=', run.id),
            ('create_date', '>=', datetime.now() - timedelta(hours=24)),
        ], order='id desc', limit=10)
    calls = []
    for r in runs:
        try:
            calls += json.loads(r.tool_calls_log or '[]')
        except Exception:
            continue
    for c in calls:
        out = c.get('output') or {}
        if not isinstance(out, dict):
            continue
        if c.get('tool_name') == 'search_products':
            for p in out.get('products') or []:
                known.append((_tokens(p.get('name')), float(p.get('price') or 0)))
        elif c.get('tool_name') == 'create_sale_order':
            for ln in out.get('lines') or []:
                known.append((_tokens(ln.get('product')), float(ln.get('price_unit') or 0)))
    return known


def _offer_prices(env):
    prices = set()
    for off in env['cristal.agent.offer'].sudo().search([('active', '=', True)]):
        for m in re.findall(r'\$\s?(\d{1,3}(?:\.\d{3})*|\d+)', off.description or ''):
            prices.add(float(m.replace('.', '')))
    return prices


def verify_prices(env, run, body_html):
    """Devuelve la lista de líneas con un precio por litro NO verificado (vacía = OK)."""
    if not run or not body_html:
        return []
    plain = re.sub(r'<\s*(br|/p|/li)\s*/?>', '\n', body_html, flags=re.IGNORECASE)
    plain = re.sub(r'<[^>]+>', ' ', plain)
    known = _known_prices_from_run(run)
    # v1.36: el precio con 20% solo vale para clientes con derecho a la 1ra compra.
    factors = _ALLOWED_FACTORS
    if run.partner_id and first_purchase_discount_status(env, run.partner_id)[0] != 'allowed':
        factors = tuple(f for f in _ALLOWED_FACTORS if f != 0.8)
    # Vocabulario de productos: nombres del catálogo mayorista + lo que devolvieron
    # las tools. Solo se controla un precio si el texto nombra un producto real
    # (así "Te paso el precio: $408/L" no se bloquea por "te paso").
    vocab = set()
    for toks, _p in known:
        vocab |= toks
    catalog = env['product.product'].sudo().search(
        [('sale_ok', '=', True), ('product_tmpl_id.is_mayorista_catalog', '=', True)])
    for prod in catalog:
        vocab |= _tokens(prod.name)
    offers = None
    problems = []
    for line in plain.split('\n'):
        prev_end = 0
        for m in _RE_PRICE_PER_L.finditer(line):
            price = float(m.group(1).replace('.', ''))
            # Solo el tramo entre el precio anterior y este (dos precios por línea).
            segment = line[prev_end:m.start()].split('•')[-1]
            prev_end = m.end()
            mention = _tokens(segment) & vocab
            if not mention:
                continue  # no nombra un producto: no se puede controlar
            candidates = [p for toks, p in known if toks & mention]
            ok = any(abs(price - p * f) <= 1.0 for p in candidates for f in factors)
            if not ok:
                if offers is None:
                    offers = _offer_prices(env)
                ok = price in offers
            if not ok:
                problems.append(line.strip()[:160])
    return problems


# ─────────────────────── 20% de primera compra: SOLO Río Cuarto (v1.36) ───────────────────────
# Joaco (13/10): el 20% OFF de primera compra es SOLO para clientes de Río Cuarto /
# Las Higueras. A los de la ruta del camión (truck_circuit_id) y a los de fuera de
# zona NUNCA se les aplica ni se les ofrece. Casos reales: S06359 (Any, Coronel
# Moldes) y S06367 (Miriancordoba, Vicuña Mackenna) salieron con 20% en cada línea.
FIRST_PURCHASE_ZONES = ('rio_cuarto', 'las_higueras')


def first_purchase_discount_status(env, partner):
    """('allowed' | 'blocked' | 'unknown', motivo).
    - allowed: cliente de Río Cuarto / Las Higueras.
    - blocked: ruta del camión (circuito) o fuera de zona.
    - unknown: todavía no sabemos la localidad → no se ofrece hasta saberla."""
    if not partner:
        return 'unknown', 'sin cliente'
    if partner.truck_circuit_id:
        return 'blocked', f"cliente de la ruta del camión ({partner.truck_circuit_id.name})"
    zone = partner.agent_zone or 'unknown'
    if zone in ('fuera_zona', 'ruta_camion'):
        return 'blocked', 'cliente de la zona/fuera de zona (no es Río Cuarto)'
    if zone in FIRST_PURCHASE_ZONES:
        return 'allowed', 'cliente de Río Cuarto / Las Higueras'
    city = (partner.city or '').strip()
    if not city:
        return 'unknown', 'todavía no sé la localidad'
    info = env['cristal.agent.circuit'].sudo().classify_city(city)
    if info.get('kind') == 'rio_cuarto':
        return 'allowed', 'cliente de Río Cuarto / Las Higueras'
    if info.get('kind') in ('circuit', 'fuera_zona'):
        return 'blocked', f"{info.get('canonical') or city} no es Río Cuarto"
    return 'unknown', 'localidad sin confirmar'


_RE_FIRST_PURCHASE_OFFER = re.compile(
    r'[^.!?\n<]*(?:20\s?%|veinte por ciento)[^.!?\n<]*(?:[.!?]|(?=<)|$)', re.IGNORECASE)


def strip_first_purchase_offer(body_html):
    """Saca las oraciones que mencionan el 20% (último recurso del control al enviar)."""
    return _RE_FIRST_PURCHASE_OFFER.sub('', body_html or '').replace('<p></p>', '')


def mentions_first_purchase_discount(body_html):
    plain = re.sub(r'<[^>]+>', ' ', body_html or '')
    return bool(re.search(r'20\s?%|veinte por ciento', plain, re.IGNORECASE))


# ─────────────────────── Feriados y horario de atención (v1.36) ───────────────────────
# Caso real: el lunes 12/10 (feriado) Claudio dijo "hoy estamos abiertos hasta las
# 19:30" y le prometió a un cliente entrega para ese día. Feriados nacionales de
# Argentina (incluye los días no laborables con fines turísticos, que la planta no
# abre). Las fechas extra (Día del Empleado de Comercio, puentes 2027 que todavía no
# se decretaron, cierres puntuales) van en config.closed_dates.
AR_HOLIDAYS = {
    # 2026
    '2026-01-01': 'Año Nuevo',
    '2026-02-16': 'Carnaval', '2026-02-17': 'Carnaval',
    '2026-03-23': 'feriado puente', '2026-03-24': 'Día de la Memoria',
    '2026-04-02': 'Malvinas / Jueves Santo', '2026-04-03': 'Viernes Santo',
    '2026-05-01': 'Día del Trabajador', '2026-05-25': 'Revolución de Mayo',
    '2026-06-15': 'Paso a la Inmortalidad de Güemes', '2026-06-20': 'Día de la Bandera',
    '2026-07-09': 'Día de la Independencia', '2026-07-10': 'feriado puente',
    '2026-08-17': 'Paso a la Inmortalidad de San Martín',
    '2026-10-12': 'Día de la Diversidad Cultural',
    '2026-11-23': 'Día de la Soberanía Nacional',
    '2026-12-07': 'feriado puente', '2026-12-08': 'Inmaculada Concepción',
    '2026-12-25': 'Navidad',
    # 2027 (los puentes turísticos de 2027 todavía no están decretados → config)
    '2027-01-01': 'Año Nuevo',
    '2027-02-08': 'Carnaval', '2027-02-09': 'Carnaval',
    '2027-03-24': 'Día de la Memoria', '2027-03-26': 'Viernes Santo',
    '2027-04-02': 'Malvinas',
    '2027-05-01': 'Día del Trabajador', '2027-05-25': 'Revolución de Mayo',
    '2027-06-20': 'Día de la Bandera', '2027-06-21': 'Paso a la Inmortalidad de Güemes',
    '2027-07-09': 'Día de la Independencia',
    '2027-08-16': 'Paso a la Inmortalidad de San Martín',
    '2027-10-11': 'Día de la Diversidad Cultural',
    '2027-11-20': 'Día de la Soberanía Nacional',
    '2027-12-08': 'Inmaculada Concepción', '2027-12-25': 'Navidad',
}
# Horario oficial de la planta (KB #89): L-V 8:30-12:30 y 15:30-19:30; sáb 9-13.
PLANT_HOURS = {0: [(8.5, 12.5), (15.5, 19.5)], 1: [(8.5, 12.5), (15.5, 19.5)],
               2: [(8.5, 12.5), (15.5, 19.5)], 3: [(8.5, 12.5), (15.5, 19.5)],
               4: [(8.5, 12.5), (15.5, 19.5)], 5: [(9.0, 13.0)], 6: []}


def _configured_closed_dates(env):
    """config.closed_dates: una fecha por línea, 'AAAA-MM-DD motivo' (o DD/MM/AAAA)."""
    out = {}
    config = env['cristal.agent.config'].sudo().get_active()
    raw = getattr(config, 'closed_dates', '') if config else ''
    for line in (raw or '').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})\s*(.*)', line) or None
        if m:
            key, why = f"{m.group(1)}-{m.group(2)}-{m.group(3)}", m.group(4)
        else:
            m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})\s*(.*)', line)
            if not m:
                continue
            key = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
            why = m.group(4)
        out[key] = (why or 'cerrado').strip(' -—:')
    return out


def closed_day_reason(env, d, _extra=None):
    """Motivo si la planta y el reparto NO operan ese día (feriado, cierre
    configurado o domingo); None si es día hábil."""
    key = d.strftime('%Y-%m-%d')
    extra = _extra if _extra is not None else _configured_closed_dates(env)
    if key in extra:
        return extra[key]
    if key in AR_HOLIDAYS:
        return f"feriado ({AR_HOLIDAYS[key]})"
    if d.weekday() == 6:
        return 'domingo'
    return None


def next_business_day(env, d, include_today=False):
    """Próximo día en que la planta abre (después de d, o d mismo si include_today)."""
    extra = _configured_closed_dates(env)
    day = d if include_today else d + timedelta(days=1)
    for _i in range(15):
        if not closed_day_reason(env, day, extra):
            return day
        day += timedelta(days=1)
    return day


def business_status(env, now=None):
    """Estado de atención AHORA (hora Argentina):
    {'open_now', 'closed_today' (motivo o None), 'next_open_text', 'next_business_day',
     'confirm_when' ('hoy' o 'el lunes 19/10')}."""
    now = now or now_ar(env)
    today = now.date()
    extra = _configured_closed_dates(env)
    closed_today = closed_day_reason(env, today, extra)
    hour = now.hour + now.minute / 60.0
    open_now = False
    later_today = None
    if not closed_today:
        for start, end in PLANT_HOURS.get(today.weekday(), []):
            if start <= hour < end:
                open_now = True
            elif hour < start and later_today is None:
                later_today = start
    if open_now or later_today is not None:
        nb = today
        start = later_today if later_today is not None else None
    else:
        nb = next_business_day(env, today)
        start = PLANT_HOURS.get(nb.weekday(), [(8.5, 12.5)])[0][0]
    if open_now:
        next_open_text = 'ahora (estamos en horario de atención)'
    else:
        h, mi = int(start), int(round((start - int(start)) * 60))
        when = 'hoy' if nb == today else fmt_day(nb)
        next_open_text = f"{when} a las {h}:{mi:02d}"
    confirm_when = 'hoy' if (open_now or nb == today) else f"el {fmt_day(nb)}"
    return {'open_now': open_now, 'closed_today': closed_today,
            'next_open_text': next_open_text, 'next_business_day': nb,
            'confirm_when': confirm_when}


def holiday_context_lines(env, now=None):
    """Líneas para el CONTEXTO TEMPORAL: si hoy/mañana/pasado no se trabaja."""
    now = now or now_ar(env)
    today = now.date()
    extra = _configured_closed_dates(env)
    lines = []
    for label, d in (('HOY', today), ('MAÑANA', today + timedelta(days=1)),
                     ('PASADO MAÑANA', today + timedelta(days=2))):
        why = closed_day_reason(env, d, extra)
        if why and why != 'domingo':
            lines.append(f"- ⛔ {label} {fmt_day(d)} es {why}: la planta y el reparto NO "
                         f"operan (sin retiros ni entregas).")
    nb = next_business_day(env, today)
    lines.append(f"- Próximo día hábil: {fmt_day(nb)}.")
    return lines


def attention_status_line(env, now=None):
    """Una línea para el bloque del mensaje entrante: ¿estamos atendiendo ahora?"""
    st = business_status(env, now)
    if st['closed_today']:
        return (f"⛔ HOY NO ATENDEMOS ({st['closed_today']}): la planta y el reparto no "
                f"operan. Decile que hoy no atendemos y que le respondemos/confirmamos "
                f"{st['confirm_when']}. NO confirmes retiros ni entregas para hoy.")
    if st['open_now']:
        return ("Planta ABIERTA ahora. Si tenés que consultar algo con Joaco, decí "
                "'lo consulto y le confirmo hoy' (nunca prometas minutos).")
    return (f"Planta CERRADA en este momento (abre {st['next_open_text']}). Si tenés que "
            f"consultar algo, decí 'lo consulto y le confirmo {st['confirm_when']}'. "
            f"NUNCA prometas 'en un minuto' ni 'ya te aviso'.")
