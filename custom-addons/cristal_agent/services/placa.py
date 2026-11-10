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
        # Odoo arranca Pillow solo con algunos formatos: muchas fotos de producto están en
        # WEBP y sin este import no se abren (faltaban la lavandina y el limpiador).
        from PIL import WebPImagePlugin  # noqa: F401
    except Exception:  # noqa: BLE001
        pass
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


BIDON_20L = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'static', 'img', 'bidon_20l.png')


def _hero_bidones(img, base_y, cx, max_h):
    """v1.62.3 — Tres bidones de 20 L SIN etiquetas (el del medio adelante, dos atrás) parados
    sobre la mesada. Qué hay adentro lo dice la tarjeta de abajo, no texto pegado en el bidón
    (Joaco, 10/11: las etiquetas sobre el bidón quedaban corridas y no se leían)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    if not os.path.exists(BIDON_20L):
        return img
    with Image.open(BIDON_20L) as im:
        src = im.convert('RGB')
    src = src.resize((src.width * 2, src.height * 2), Image.LANCZOS)
    cut = _cutout(src)
    if cut is None:
        return img
    h_c = int(min(max_h * 0.82, 400))
    front = cut.resize((int(cut.width * h_c / cut.height), h_c), Image.LANCZOS)
    h_s = int(h_c * 0.80)
    side = cut.resize((int(cut.width * h_s / cut.height), h_s), Image.LANCZOS)
    lift = int(h_c * 0.08)
    layers = [(ImageOps.mirror(side), int(cx - front.width * 0.5 - side.width * 0.62), base_y - lift),
              (side, int(cx + front.width * 0.5 - side.width * 0.38), base_y - lift),
              (front, int(cx - front.width / 2), base_y)]
    canvas = img.convert('RGBA')
    sh = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    for p, x, y in layers:
        sd.ellipse((x + p.width * 0.06, y - 16, x + p.width * 0.94, y + 18), fill=(0, 0, 0, 120))
    canvas = Image.alpha_composite(canvas, sh.filter(ImageFilter.GaussianBlur(12)))
    for p, x, y in layers:
        canvas.alpha_composite(p, (x, y - p.height))
    return canvas


def _granel_card(img, box, header, items):
    """Tarjeta blanca con encabezado naranja y la lista de productos en letra grande."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = box
    sh = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x0 + 4, y0 + 8, x1 + 4, y1 + 8), radius=28,
                                         fill=(0, 0, 0, 90))
    img.alpha_composite(sh)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((x0, y0, x1, y1), radius=28, fill=WHITE)
    hh = 66
    d.rounded_rectangle((x0, y0, x1, y0 + hh), radius=28, fill=ORANGE)
    d.rectangle((x0, y0 + hh - 30, x1, y0 + hh), fill=ORANGE)
    fh = _fit(d, header, _FONT_BLACK, 38, x1 - x0 - 60)
    d.text(((x0 + x1) / 2, y0 + hh / 2 + 2), header, font=fh, fill=WHITE, anchor='mm')
    cols = 1 if len(items) <= 3 else 2
    rows = -(-len(items) // cols)
    top, bottom = y0 + hh + 14, y1 - 14
    rh = (bottom - top) / max(1, rows)
    colw = (x1 - x0 - 60) / cols
    size = int(min(42, rh * 0.62))
    # un solo tamaño para toda la lista (el que entra en la más larga), nunca menos de 30
    size = min([size] + [getattr(_fit(d, it, _FONT_BOLD, size, colw - 50, min_size=30), 'size', size)
                         for it in items])
    f = _font(_FONT_BOLD, size)
    for i, it in enumerate(items):
        c, r = (i // rows, i % rows) if cols == 2 else (0, i)
        cx0 = x0 + 36 + c * colw
        cy = top + rh * r + rh / 2
        while d.textlength(it, font=f) > colw - 50 and len(it) > 4:
            it = it[:-2].rstrip() + '…'
        d.ellipse((cx0, cy - 9, cx0 + 18, cy + 9), fill=ORANGE)
        d.text((cx0 + 32, cy + 1), it, font=f, fill=NAVY, anchor='lm')


def _render_granel(dia, titulo, pueblos, promo, condiciones, cierre, items, scene, story, quality):
    """v1.62.3 — Placa mayorista de productos A GRANEL: título, tres bidones de 20 L limpios
    en el escenario, tarjeta con lo que se vende y CTA. Pensada para leerse en el celular."""
    from PIL import Image, ImageDraw
    HH = STORY_H if story else H
    top = 250 if story else 48
    n_title = len([x for x in (titulo or '').split('|') if x])
    n_pueb = len([x for x in (pueblos or '').split('|') if x])
    promo_lines = [x for x in (promo or '').split('|') if x]
    title_end = top + (72 if dia else 0) + 84 * n_title + 40 * n_pueb + 6
    bottom = HH - (300 if story else 40)
    cta_y = bottom - 66
    cond_h = 46 if condiciones else 0
    promo_h = 76 * len(promo_lines)
    promo_y = cta_y - 22 - cond_h - promo_h
    rows = len(items) if len(items) <= 3 else -(-len(items) // 2)
    card_h = 66 + 28 + rows * (64 if story else 56)
    card_y1 = promo_y - 20
    card_y0 = card_y1 - card_h
    base_y = card_y0 - 14
    vis_h = base_y - title_end - 30
    sc = _scene(scene, HH, surface_at=base_y - 34)[0] if scene else None
    if sc is None:
        sc = Image.new('RGB', (W, HH), NAVY)
    img = sc.convert('RGBA')
    _gradient(img, 0, title_end + 20, 235, 110)
    _gradient(img, card_y0 + card_h // 2, HH, 170, 250)
    if vis_h >= 200:
        img = _hero_bidones(img, base_y, W // 2, vis_h)
    _granel_card(img, (40, card_y0, W - 40, card_y1), 'EN BIDONES DE 20 L', items)
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
    yb = promo_y
    for line in promo_lines:
        _shadow(draw, (44, yb), line, _fit(draw, line, _FONT_BLACK, 72, 990), ORANGE)
        yb += 76
    if condiciones:
        _shadow(draw, (48, yb + 4), condiciones, _fit(draw, condiciones, _FONT_BOLD, 30, 990), WHITE)
    if cierre:
        f = _fit(draw, cierre, _FONT_BLACK, 34, W - 200)
        tw = draw.textlength(cierre, font=f)
        _pill(draw, cierre, f, int((W - tw - 44) / 2), cta_y, WHITE, DARK)
    out = io.BytesIO()
    img.convert('RGB').save(out, format='JPEG', quality=quality, optimize=True)
    return out.getvalue()


SCENE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'static', 'img', 'escenas')
# v1.61.3 — Escenarios generados SIN productos ni texto (cocina, lavadero, baño, pileta,
# almacén, depósito). Los productos se ponen encima con sus fotos reales, así ninguna etiqueta
# es inventada. La superficie vacía empieza a ~68% del alto de la foto 9:16.
SCENES = ('cocina', 'lavadero', 'bano', 'pileta', 'almacen', 'deposito')
SCENE_SURFACE = 0.70


def _scene(name, HH, surface_at=None):
    """Fondo de escenario a 1080×HH con el borde de la mesada en `surface_at` (por defecto a
    2/3 del alto): si hace falta, agranda y recorta. Devuelve (imagen RGB, y de la superficie)."""
    from PIL import Image
    path = os.path.join(SCENE_DIR, f"{name}.jpg")
    if not name or not os.path.exists(path):
        return None, None
    with Image.open(path) as im:
        img = im.convert('RGB')
    img = img.resize((W, int(img.height * W / img.width)))
    target = int(surface_at if surface_at is not None else HH * 0.66)
    s = img.height * SCENE_SURFACE
    f = max(1.0, target / s, (HH - target) / max(1.0, img.height - s))
    if f > 1.0:
        nw, nh = int(W * f) + 1, int(img.height * f) + 1
        img = img.resize((nw, nh))
        left = (nw - W) // 2
        img = img.crop((left, 0, left + W, nh))
        s *= f
    top = int(max(0, min(img.height - HH, s - target)))
    img = img.crop((0, top, W, top + HH))
    return img, int(s - top)


def _cutout(photo):
    """Saca el fondo de la foto de estudio. v1.61.5: el fondo se toma como lo CLARO y SIN COLOR
    (blanco, gris claro del piso, reflejos) conectado con los bordes — un bidón blanco con su
    contorno no se agujerea. Si la foto no tiene fondo para sacar (el producto llena el cuadro:
    trapos, paños, bolsas) devuelve None y se muestra en tarjeta."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    rgb = photo.convert('RGB')
    rgb.thumbnail((700, 700))
    w, h = rgb.size
    r, g, b = rgb.split()
    lo = ImageChops.darker(ImageChops.darker(r, g), b)
    hi = ImageChops.lighter(ImageChops.lighter(r, g), b)
    light = lo.point(lambda v: 255 if v >= 200 else 0)
    flat = ImageChops.subtract(hi, lo).point(lambda v: 255 if v <= 28 else 0)
    cand = ImageChops.multiply(light, flat)          # 255 = parece fondo
    px = cand.load()
    step = max(1, min(w, h) // 60)
    border = ([(x, 0) for x in range(0, w, step)] + [(x, h - 1) for x in range(0, w, step)]
              + [(0, y) for y in range(0, h, step)] + [(w - 1, y) for y in range(0, h, step)])
    for sx, sy in border:
        if px[sx, sy] == 255:
            ImageDraw.floodfill(cand, (sx, sy), 128)
    bg = cand.point(lambda v: 255 if v == 128 else 0)
    frac = sum(bg.histogram()[255:]) / float(w * h)
    if frac < 0.10:
        return None
    mask = ImageChops.invert(bg)
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.1))
    out = rgb.convert('RGBA')
    out.putalpha(mask)
    # v1.63.2 — La caja se mide sobre lo que tiene "tinta" (no casi blanco): restos claros
    # invisibles ensanchaban la caja y un palo dejaba de verse largo y finito.
    ink = ImageChops.lighter(lo.point(lambda v: 255 if v < 215 else 0),
                             ImageChops.subtract(hi, lo).point(lambda v: 255 if v > 28 else 0))
    core = ImageChops.multiply(ink, mask.point(lambda v: 255 if v > 128 else 0))
    box = core.getbbox() or mask.point(lambda v: 255 if v > 40 else 0).getbbox()
    if box:
        box = (max(0, box[0] - 4), max(0, box[1] - 4), min(w, box[2] + 4), min(h, box[3] + 4))
    return out.crop(box) if box else None


def _card(photo, h_t):
    """Foto en tarjeta blanca redondeada (para lo que no se puede recortar)."""
    from PIL import Image, ImageDraw
    p = photo.convert('RGB').copy()
    inner = int(h_t * 0.86)
    p.thumbnail((inner, inner), Image.LANCZOS)
    pad = max(8, int(h_t * 0.06))
    cw, ch = p.width + 2 * pad, p.height + 2 * pad
    card = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=max(10, pad * 2),
                                           fill=(255, 255, 255, 255))
    card.paste(p, (pad, pad))
    return card


def _lineup(img, photos, base_y, x0, x1, max_h):
    """Para los productos (recortados) sobre la superficie del escenario, con sombra.
    Hasta 5 en una fila; más, en dos filas (la de atrás un poco más arriba y más chica)."""
    from PIL import Image, ImageDraw, ImageFilter
    cut, seen = [], set()
    for p in photos:
        sig = p.resize((16, 16)).tobytes()
        if sig in seen:          # misma foto (variantes con la misma imagen): una sola vez
            continue
        seen.add(sig)
        c = _cutout(p)
        if c is None:
            card = _card(p, 600)
            c = Image.new('RGBA', (card.width, int(card.height * 1.25)), (0, 0, 0, 0))
            c.alpha_composite(card, (0, c.height - card.height))
        cut.append(c)
    # v1.63.2 — Lo largo y finito (palos, cabos, secadores) va ACOSTADO sobre la mesada, no
    # parado: parado queda como un hilo y achica todo lo demás (kits mopa/secador/barrido).
    lying, stand = [], []
    for c in cut:
        ar = c.height / max(1, c.width)
        if ar > 3.5:
            lying.append(c.rotate(90, expand=True))
        elif ar < 1 / 3.5:
            lying.append(c)
        else:
            stand.append(c)
    if lying:
        return _lineup_lying(img, stand, lying, base_y, x0, x1, max_h)
    # Una fila si entran a buen tamaño; si no (más de 5, o productos anchos como bolsas y
    # esponjas que quedarían chiquitos), dos filas.
    natural = sum(c.width * max_h / c.height for c in cut) + 14 * (len(cut) - 1)
    one_row = len(cut) <= 3 or (len(cut) <= 5 and natural <= (x1 - x0) * 1.15)
    rows = [cut] if one_row else [cut[:len(cut) // 2], cut[len(cut) // 2:]]
    layers = []
    for ri, row in enumerate(rows):
        back = len(rows) == 2 and ri == 0
        if len(rows) == 1:
            h_t, y_b = max_h, base_y
        else:   # la de atrás asoma por encima de la de adelante
            h_t = int(max_h * (0.55 if back else 0.60))
            y_b = base_y - (int(max_h * 0.26) if back else 0)
        # Altura pareja en la fila (prolijo); lo largo y finito ya se acostó antes.
        scaled = [p.resize((max(1, int(p.width * h_t / p.height)), h_t)) for p in row]
        gap = 14
        total = sum(p.width for p in scaled) + gap * (len(scaled) - 1)
        avail = x1 - x0
        if total > avail:
            f = avail / total
            scaled = [p.resize((max(1, int(p.width * f)), max(1, int(p.height * f)))) for p in scaled]
            total = sum(p.width for p in scaled) + gap * (len(scaled) - 1)
        x = x0 + (avail - total) // 2
        for p in scaled:
            layers.append((p, x, y_b))
            x += p.width + gap
    canvas = img.convert('RGBA')
    shadow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for p, x, y in layers:
        sd.ellipse((x + p.width * 0.08, y - 14, x + p.width * 0.92, y + 16), fill=(0, 0, 0, 110))
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(10)))
    for p, x, y in layers:
        canvas.alpha_composite(p, (int(x), int(y - p.height)))
    return canvas.convert('RGB')


def _lineup_lying(img, stand, lying, base_y, x0, x1, max_h):
    """Productos parados atrás y los largos acostados adelante, a lo ancho de la mesada. Si
    todo es largo (kit secador), foto cenital: cada pieza a lo ancho, una debajo de la otra.
    `stand` y `lying` ya vienen recortados (RGBA) y `lying` ya horizontal."""
    from PIL import Image, ImageDraw, ImageFilter
    avail = x1 - x0
    canvas = img.convert('RGBA')
    shadow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    layers = []

    def fit_w(p, w, h_max):
        f = min(w / p.width, h_max / p.height)
        return p.resize((max(1, int(p.width * f)), max(1, int(p.height * f))), Image.LANCZOS)

    if stand:
        lay = [fit_w(p, avail * 0.88, max_h * 0.16) for p in lying]
        band = sum(p.height for p in lay) + 12 * (len(lay) - 1)
        y_s = base_y - int(band * 0.55)
        h_s = int(max_h - band * 0.55)
        cell = (avail - 24 * (len(stand) - 1)) / len(stand)
        sc = [fit_w(p, cell, h_s) for p in stand]
        total = sum(p.width for p in sc) + 24 * (len(sc) - 1)
        x = x0 + (avail - total) // 2
        for p in sc:
            layers.append((p, x, y_s))
            sd.ellipse((x + p.width * 0.08, y_s - 14, x + p.width * 0.92, y_s + 16), fill=(0, 0, 0, 110))
            x += p.width + 24
        y = base_y
        for p in lay:                      # adelante, de abajo hacia arriba
            x = x0 + (avail - p.width) // 2
            layers.append((p, x, y))
            sd.rounded_rectangle((x + 10, y - 6, x + p.width - 10, y + 10), radius=8, fill=(0, 0, 0, 120))
            y -= p.height + 12
    else:                                  # foto cenital: todo a lo ancho
        slot = max_h / len(lying)
        top = base_y - max_h
        for i, p in enumerate(lying):
            q = fit_w(p, avail * 0.88, slot * 0.78)
            x = x0 + (avail - q.width) // 2
            y = int(top + slot * i + (slot + q.height) / 2)
            layers.append((q, x, y))
            sd.rounded_rectangle((x + 12, y - q.height + 14, x + q.width - 4, y + 12), radius=12,
                                 fill=(0, 0, 0, 90))
    canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(10)))
    for p, x, y in layers:
        canvas.alpha_composite(p, (int(x), int(y - p.height)))
    return canvas.convert('RGB')


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
           products=None, scene=None):
    """Devuelve los bytes JPEG de la placa. Los textos multilínea usan '|' como separador.
    `story=True` arma 1080×1920 (9:16) dejando libres las franjas de arriba y abajo que tapa
    la interfaz de Instagram.
    `products`: lista de fotos reales (bytes) de las variantes de los productos; si viene, la
    placa se arma con ellas (v1.61.3). `base` (foto de IA) queda solo como respaldo viejo."""
    from PIL import Image, ImageDraw
    # v1.62.3: lo a granel viene como ('GRANEL', 'Suavizante') / ('ITEM', 'Base limpiador 1 L')
    granel = [x for x in (products or []) if isinstance(x, tuple)]
    if any(k == 'GRANEL' for k, _ in granel):
        items = list(dict.fromkeys(lbl for _, lbl in granel))[:6]
        return _render_granel(dia, titulo, pueblos, promo, condiciones, cierre, items,
                              scene, story, quality)
    products = [x for x in (products or []) if not isinstance(x, tuple)]
    HH = STORY_H if story else H
    top = 250 if story else 48
    photos = [p for p in (_load_photo(b) for b in (products or [])) if p is not None]
    if photos:
        n_title = len([x for x in (titulo or '').split('|') if x])
        n_pueb = len([x for x in (pueblos or '').split('|') if x])
        z0 = top + (82 if dia else 0) + 84 * n_title + 40 * n_pueb + 26
        z1 = HH - 445 - (300 if story else 0) - 24
        sc = _scene(scene, HH, surface_at=z1 - 30)[0] if scene else None
        if sc is not None:
            # Escenario sin productos + los productos reales parados en la superficie.
            img = _lineup(sc, photos[:6], z1 + 20, 50, W - 50, z1 - z0 - 20)
        else:
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
    if photos and sc is not None:
        # Con escenario: franjas oscuras solo donde va el texto, los productos quedan limpios.
        _gradient(img, 0, z0, 235, 150)
        _gradient(img, z1 + 30, HH, 150, 245)
    elif not photos:
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


def render_combo(name, price, items, loose=None, footer=None, story=False, quality=88, scene=None,
                 origin="Fabricado en Río Cuarto"):
    """v1.61.3 — Placa de un combo para la casa con las FOTOS REALES de lo que trae.
    items = [(nombre corto, bytes de la foto de la variante)], price/loose en pesos.
    Fondo claro, banda naranja con el nombre, grilla de productos con su nombre, precio en
    círculo y ahorro contra el precio suelto. Sin imágenes de IA."""
    from PIL import Image, ImageDraw
    HH = STORY_H if story else H
    top = 210 if story else 0
    bottom_safe = 260 if story else 0
    photos = [(n, p) for n, p in ((n, _load_photo(b)) for n, b in items) if p is not None]
    sc = _scene(scene, HH, surface_at=HH - bottom_safe - 380)[0] if scene else None
    img = sc if sc is not None else Image.new('RGB', (W, HH), CREAM)
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

    z0 = top + band_h + 28
    z1 = HH - bottom_safe - 330
    if sc is not None:
        # Escenario + los productos reales parados en la mesada (sin etiquetas inventadas).
        img = _lineup(img, [p for _n, p in photos], z1 - 6, 40, W - 40, z1 - z0 - 10)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((28, z1 + 4, W - 28, HH - bottom_safe - 76), radius=26, fill=WHITE)
    cells = [] if sc is not None else _grid([p for _n, p in photos], 50, z0, W - 50, z1, gap=22)
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
    d.text((tx, yb + 170), origin or "", font=_fit(d, origin or "", _FONT_BOLD, 32, W - tx - 40), fill=DARK)

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


def render_angle(angle, ctx, base=None, products=None, scene=None):
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
                  fmt(spec["promo"]), fmt(spec["detalle"]), condiciones, cierre, products=products, scene=scene)
