# -*- coding: utf-8 -*-
"""
Generador de placas 1080×1350 (4:5) para la pauta de la ruta del camión — v1.58.

Misma composición que docs/placa_ruta2.ps1 (foto a sangre, degradé arriba y abajo,
pill de fecha, título, pueblos, promo grande, detalle, condiciones y pill de cierre),
pero en el servidor con Pillow para que el cron la genere sola 7 días antes de cada
salida. Las fotos base viven en static/img/placa/ (imágenes IA de Joaco, sin texto).

Un ángulo de venta por placa (ver ANGLES): el motor compara ángulos, no "anuncios".
"""
import io
import logging
import os

_logger = logging.getLogger(__name__)

W, H = 1080, 1350
ORANGE = (242, 106, 27)
WHITE = (255, 255, 255)
DARK = (25, 25, 25)
NAVY = (10, 14, 25)

BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'static', 'img', 'placa')
BASES = {
    'joaco_camion': 'joaco_camion.jpg',
    'joaco_deposito': 'joaco_deposito.jpg',
    'pallet_regalo': 'pallet_regalo.jpg',
    'camion_cargado': 'camion_cargado.jpg',
}
# Fuentes: lo que suele haber en Odoo.sh (Debian); si no, la de Pillow.
_FONT_BOLD = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    'C:/Windows/Fonts/arialbd.ttf',
]
_FONT_BLACK = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    'C:/Windows/Fonts/ariblk.ttf',
]

# Ángulo → (base por defecto, título, promo, detalle); {pueblos}, {dia}, {cierre},
# {promo_corta}, {envio} se completan con los datos de la salida.
ANGLES = {
    'REGALO': dict(
        base='pallet_regalo',
        titulo='{promo_l1}|{promo_l2}',
        promo='EL CAMIÓN PASA|POR TU PUEBLO',
        detalle='Mezclados como quieras: jabón, suavizante, cloro, detergente…',
    ),
    'LOGISTICA': dict(
        base='joaco_camion',
        titulo='EL CAMIÓN LLEGA|A TU PUEBLO',
        promo='TE LO DEJAMOS|EN TU NEGOCIO',
        detalle='{promo_corta}, mezclados como quieras',
    ),
    'FABRICA': dict(
        base='joaco_deposito',
        titulo='SOMOS FÁBRICA|SIN INTERMEDIARIOS',
        promo='PRECIO DE FÁBRICA|EN TU NEGOCIO',
        detalle='Jabón, suavizante, lavandina, cloro, detergente y desengrasante en bidones de 20 L',
    ),
    'MARGEN': dict(
        base='camion_cargado',
        titulo='COMPRÁS A GRANEL|GANÁS POR LITRO',
        promo='FRACCIONÁS|Y REVENDÉS',
        detalle='Bidones de 20 L a precio de fábrica, directo al negocio',
    ),
    'URGENCIA': dict(
        base='joaco_camion',
        titulo='ÚLTIMOS LUGARES|EN EL CAMIÓN',
        promo='{dia_corto}|PASA POR TU PUEBLO',
        detalle='{promo_corta}, mezclados como quieras',
    ),
}


def _font(paths, size):
    from PIL import ImageFont
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:  # noqa: BLE001
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _fit(draw, text, paths, max_size, max_width, min_size=16):
    size = max_size
    while size > min_size:
        f = _font(paths, size)
        if draw.textlength(text, font=f) <= max_width:
            return f
        size -= 2
    return _font(paths, min_size)


def _shadow(draw, xy, text, font, fill):
    x, y = xy
    draw.text((x + 3, y + 4), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=fill)


def _gradient(img, y0, y1, a0, a1):
    from PIL import Image
    h = y1 - y0
    col = Image.new('L', (1, h))
    col.putdata([int(a0 + (a1 - a0) * i / max(1, h - 1)) for i in range(h)])
    band = Image.new('RGBA', (W, h), NAVY + (0,))
    band.putalpha(col.resize((W, h)))
    img.alpha_composite(band, (0, y0))


def _pill(draw, text, font, x, y, bg, fg):
    tw = draw.textlength(text, font=font)
    th = getattr(font, 'size', None) or font.getbbox('Ag')[3]
    w, h = int(tw + 44), int(th + 26)
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=bg)
    draw.text((x + 22, y + 10), text, font=font, fill=fg)
    return w, h


STORY_H = 1920  # v1.60: historia 9:16


def render(base, dia, titulo, pueblos, promo, detalle, condiciones, cierre, quality=86, story=False):
    """Devuelve los bytes JPEG de la placa. `base` es una clave de BASES o una ruta.
    Los textos multilínea usan '|' como separador. `story=True` arma 1080×1920 (9:16) dejando
    libres las franjas de arriba y abajo que tapa la interfaz de Instagram."""
    from PIL import Image, ImageDraw
    HH = STORY_H if story else H
    top = 250 if story else 48
    path = BASES.get(base, base)
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    with Image.open(path) as im:
        img = im.convert('RGB')
    if img.size != (W, HH):
        # recorte centrado a la proporción pedida y redimensión
        ratio = W / HH
        cw, ch = img.width, int(img.width / ratio)
        if ch > img.height:
            ch, cw = img.height, int(img.height * ratio)
        cx, cy = (img.width - cw) // 2, (img.height - ch) // 2
        img = img.crop((cx, cy, cx + cw, cy + ch)).resize((W, HH))
    img = img.convert('RGBA')
    _gradient(img, 0, top + 472, 230, 0)
    _gradient(img, HH - 550 - (top - 48), HH, 0, 245)
    draw = ImageDraw.Draw(img)

    y = top
    if dia:
        f = _fit(draw, dia, _FONT_BLACK, 34, 700)
        _, h = _pill(draw, dia, f, 48, y, ORANGE, WHITE)
        y += h + 22
    for line in (titulo or '').split('|'):
        if line:
            _shadow(draw, (44, y), line, _fit(draw, line, _FONT_BLACK, 78, 980), WHITE)
            y += 84
    y += 6
    for line in (pueblos or '').split('|'):
        if line:
            _shadow(draw, (48, y), line, _fit(draw, line, _FONT_BOLD, 30, 990), WHITE)
            y += 40
    _shadow(draw, (W - 268, top + 4), 'CRISTAL', _font(_FONT_BLACK, 44), ORANGE)
    _shadow(draw, (W - 172, top + 54), 'Química', _font(_FONT_BOLD, 26), ORANGE)

    yb = HH - 445 - (300 if story else 0)
    for line in (promo or '').split('|'):
        if line:
            _shadow(draw, (44, yb), line, _fit(draw, line, _FONT_BLACK, 84, 990), ORANGE)
            yb += 92
    if detalle:
        _shadow(draw, (48, yb + 4), detalle, _fit(draw, detalle, _FONT_BOLD, 32, 990), WHITE)
        yb += 46
    if condiciones:
        _shadow(draw, (48, yb + 6), condiciones, _fit(draw, condiciones, _FONT_BOLD, 32, 990), WHITE)
        yb += 52
    if cierre:
        f = _fit(draw, cierre, _FONT_BLACK, 34, W - 200)
        tw = draw.textlength(cierre, font=f)
        _pill(draw, cierre, f, int((W - tw - 44) / 2), max(yb + 18, HH - 110 - (290 if story else 0)), WHITE, DARK)

    out = io.BytesIO()
    img.convert('RGB').save(out, format='JPEG', quality=quality, optimize=True)
    return out.getvalue()


def render_angle(angle, ctx, base=None):
    """Placa de un ángulo con el contexto de la salida:
    ctx = {dia, dia_corto, pueblos (con '|'), promo_l1, promo_l2, promo_corta,
           condiciones, cierre, cierre_urgencia, dia_urgencia}."""
    spec = ANGLES[angle]
    fmt = lambda s: (s or '').format(**ctx)  # noqa: E731
    dia = ctx.get('dia_urgencia') if angle == 'URGENCIA' else ctx.get('dia')
    cierre = ctx.get('cierre_urgencia') if angle == 'URGENCIA' else ctx.get('cierre')
    condiciones = ctx.get('condiciones')
    if angle in ('FABRICA', 'MARGEN'):
        condiciones = f"{ctx.get('promo_corta')} · {ctx.get('envio')}"
    return render(base or spec['base'], dia, fmt(spec['titulo']), ctx.get('pueblos'),
                  fmt(spec['promo']), fmt(spec['detalle']), condiciones, cierre)
