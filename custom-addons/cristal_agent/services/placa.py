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
CREAM = (247, 244, 238)
GREY = (90, 90, 90)


def _load_photo(data):
    """Foto real de un producto (bytes) → RGBA recortada a su contenido. Las fotos de Odoo
    vienen sobre fondo blanco: se recorta el blanco sobrante para que el producto llene el
    lugar. None si no se puede abrir."""
    from PIL import Image, ImageChops
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:  # noqa: BLE001
        return None
    im = im.convert('RGBA')
    bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
    flat = Image.alpha_composite(bg, im).convert('RGB')
    diff = ImageChops.difference(flat, Image.new('RGB', flat.size, (255, 255, 255)))
    box = diff.convert('L').point(lambda v: 255 if v > 18 else 0).getbbox()
    if box:
        pad = 8
        box = (max(0, box[0] - pad), max(0, box[1] - pad),
               min(flat.width, box[2] + pad), min(flat.height, box[3] + pad))
        flat = flat.crop(box)
    return flat


def _grid(photos, x0, y0, x1, y1, gap=18):
    """Posiciones (x, y, w, h) de una grilla para N fotos dentro del rectángulo."""
    n = len(photos)
    if not n:
        return []
    cols = n if n <= 4 else (3 if n in (5, 6, 9) else 4)
    rows = -(-n // cols)
    cw = (x1 - x0 - gap * (cols - 1)) // cols
    ch = (y1 - y0 - gap * (rows - 1)) // rows
    cells = []
    for i in range(n):
        r, c = divmod(i, cols)
        in_row = min(cols, n - r * cols)
        off = ((cols - in_row) * (cw + gap)) // 2   # última fila centrada
        cells.append((x0 + off + c * (cw + gap), y0 + r * (ch + gap), cw, ch))
    return cells


def _paste_fit(img, photo, cell):
    from PIL import Image
    x, y, w, h = cell
    p = photo.copy()
    p.thumbnail((w, h), Image.LANCZOS)
    img.paste(p, (x + (w - p.width) // 2, y + (h - p.height) // 2))


def _products_background(photos, HH, zone):
    """v1.61.3 — Fondo con FOTOS REALES de los productos (las de la variante en Odoo), sin
    imágenes de IA (Joaco, 10/11/2026: "se ven feas, muy IA", etiquetas inventadas). Fondo
    oscuro de marca y un panel claro con los productos en grilla."""
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (W, HH), NAVY)
    top_c, bot_c = (28, 36, 58), NAVY
    d = ImageDraw.Draw(img)
    for yy in range(HH):
        t = yy / max(1, HH - 1)
        d.line([(0, yy), (W, yy)], fill=tuple(int(top_c[i] + (bot_c[i] - top_c[i]) * t) for i in range(3)))
    y0, y1 = zone
    d.rounded_rectangle((36, y0, W - 36, y1), radius=28, fill=CREAM)
    d.rectangle((36, y1 - 10, W - 36, y1), fill=ORANGE)
    for cell, ph in zip(_grid(photos, 60, y0 + 22, W - 60, y1 - 32), photos):
        _paste_fit(img, ph, cell)
    return img


def render(base, dia, titulo, pueblos, promo, detalle, condiciones, cierre, quality=86, story=False,
           products=None):
    """Devuelve los bytes JPEG de la placa. Los textos multilínea usan '|' como separador.
    `story=True` arma 1080×1920 (9:16) dejando libres las franjas de arriba y abajo que tapa
    la interfaz de Instagram.
    `products`: lista de fotos reales (bytes) de las variantes de los productos; si viene, la
    placa se arma con ellas (v1.61.3). `base` (foto de IA) queda solo como respaldo viejo."""
    from PIL import Image, ImageDraw
    HH = STORY_H if story else H
    top = 250 if story else 48
    photos = [p for p in (_load_photo(b) for b in (products or [])) if p is not None]
    if photos:
        n_title = len([x for x in (titulo or '').split('|') if x])
        n_pueb = len([x for x in (pueblos or '').split('|') if x])
        z0 = top + (82 if dia else 0) + 84 * n_title + 40 * n_pueb + 26
        z1 = HH - 445 - (300 if story else 0) - 24
        img = _products_background(photos, HH, (z0, z1))
    else:
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
    if not photos:
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


def render_combo(name, price, items, loose=None, footer=None, story=False, quality=88):
    """v1.61.3 — Placa de un combo para la casa con las FOTOS REALES de lo que trae.
    items = [(nombre corto, bytes de la foto de la variante)], price/loose en pesos.
    Fondo claro, banda naranja con el nombre, grilla de productos con su nombre, precio en
    círculo y ahorro contra el precio suelto. Sin imágenes de IA."""
    from PIL import Image, ImageDraw
    HH = STORY_H if story else H
    top = 210 if story else 0
    bottom_safe = 260 if story else 0
    img = Image.new('RGB', (W, HH), CREAM)
    d = ImageDraw.Draw(img)
    money = lambda v: '$' + f'{int(round(v or 0)):,}'.replace(',', '.')  # noqa: E731

    # Banda superior con el nombre del combo
    band_h = 230
    d.rectangle((0, top, W, top + band_h), fill=ORANGE)
    words = (name or '').upper().replace('COMBO ', 'COMBO|', 1).split('|')
    yy = top + 30
    for line in words[:2]:
        f = _fit(d, line, _FONT_BLACK, 84, W - 120)
        tw = d.textlength(line, font=f)
        d.text(((W - tw) / 2, yy), line, font=f, fill=WHITE)
        yy += 92

    # Grilla de productos (foto + nombre)
    photos = [(n, p) for n, p in ((n, _load_photo(b)) for n, b in items) if p is not None]
    z0 = top + band_h + 28
    z1 = HH - bottom_safe - 330
    cells = _grid([p for _n, p in photos], 50, z0, W - 50, z1, gap=22)
    for cell, (label, ph) in zip(cells, photos):
        x, y, w, h = cell
        d.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=WHITE)
        cap = 40 if h > 200 else 32
        _paste_fit(img, ph, (x + 10, y + 10, w - 20, h - cap - 14))
        f = _fit(d, label, _FONT_BOLD, 24, w - 16, min_size=14)
        tw = d.textlength(label, font=f)
        d.text((x + (w - tw) / 2, y + h - cap), label, font=f, fill=GREY)

    # Precio y ahorro
    yb = HH - bottom_safe - 300
    r = 118
    cx, cy = 48 + r, yb + r + 10
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ORANGE)
    ptxt = money(price)
    f = _fit(d, ptxt, _FONT_BLACK, 62, 2 * r - 26)
    tw = d.textlength(ptxt, font=f)
    d.text((cx - tw / 2, cy - 36), ptxt, font=f, fill=WHITE)
    tx = cx + r + 34
    if loose and loose > price:
        d.text((tx, yb + 40), f"Suelto {money(loose)}", font=_font(_FONT_BOLD, 40), fill=GREY)
        d.text((tx, yb + 96), f"Ahorrás {money(loose - price)}", font=_font(_FONT_BLACK, 56), fill=ORANGE)
    else:
        d.text((tx, yb + 70), "Todo junto, un solo pedido", font=_font(_FONT_BOLD, 40), fill=GREY)
    d.text((tx, yb + 170), "Fabricado en Río Cuarto", font=_font(_FONT_BOLD, 32), fill=DARK)

    # Franja inferior
    fy = HH - bottom_safe - 64
    d.rectangle((0, fy, W, fy + 64), fill=WHITE)
    foot = footer or 'Envío a domicilio $6.500 · GRATIS desde $65.000 · Pedilo por WhatsApp'
    f = _fit(d, foot, _FONT_BOLD, 30, W - 60)
    tw = d.textlength(foot, font=f)
    d.text(((W - tw) / 2, fy + 16), foot, font=f, fill=DARK)

    out = io.BytesIO()
    img.save(out, format='JPEG', quality=quality, optimize=True)
    return out.getvalue()


def render_angle(angle, ctx, base=None, products=None):
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
                  fmt(spec['promo']), fmt(spec['detalle']), condiciones, cierre, products=products)
