# -*- coding: utf-8 -*-
"""
Pauta Cristal — v1.58: registro de creativos, experimentos y contenido automático
por salida de la ruta (D-7).

Plan integral: docs/motor-pauta-contenido.md. Acá vive la parte que corre en Odoo:
- cristal.agent.creative: una fila por pieza (zona, salida, ángulo, formato, versión,
  adjunto público, ids de Meta y resultados a D+7).
- cristal.agent.experiment: hipótesis → acción → resultado del analista semanal.
- cristal.agent.pauta (abstract): cron diario que, 7 días antes de cada salida, genera
  las placas por ángulo con services/placa.py, las deja como adjuntos públicos
  (URL /website/image/ir.attachment/<id>/datas, la única que Meta acepta porque
  /web/ está bloqueada en robots.txt), registra los creativos, escribe el copy y el
  guion del video, y avisa en el canal interno. La campaña la arma la rutina semanal
  de pauta (MCP Meta) a partir de estos registros; acá no se toca Meta.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

ANGLE_SELECTION = [
    ('REGALO', 'Regalo / promo'),
    ('LOGISTICA', 'Logística: el camión llega a tu pueblo'),
    ('FABRICA', 'Fábrica: sin intermediarios'),
    ('MARGEN', 'Margen del revendedor'),
    ('URGENCIA', 'Urgencia: cierre de preventa'),
    ('PRUEBA_SOCIAL', 'Prueba social'),
    ('PRODUCTO', 'Producto estrella'),
]
FORMAT_SELECTION = [
    ('placa', 'Placa 4:5'),
    ('story', 'Story 9:16'),
    ('video', 'Video a cámara'),
    ('carrusel', 'Carrusel'),
    ('organico', 'Orgánico (Instagram / Facebook)'),
]
# v1.59 — calendario orgánico: martes y viernes; rotación de ángulos del mes.
ORGANIC_WEEKDAYS = (1, 4)
ORGANIC_ROTATION = ('LOGISTICA', 'FABRICA', 'PRODUCTO', 'MARGEN', 'PRUEBA_SOCIAL',
                    'PRODUCTO', 'FABRICA', 'MARGEN', 'PRODUCTO', 'PRUEBA_SOCIAL')
ORGANIC_SKIP = {(12, 25), (1, 1)}  # Navidad y Año Nuevo: sin posteo
BASES_ORDER = ('joaco_deposito', 'camion_cargado', 'pallet_regalo', 'joaco_camion')
ORGANIC_HASHTAGS ="#QuímicaCristal #RíoCuarto #ProductosDeLimpieza #Mayorista #VentaPorMayor"
ROUTE_ANGLES = ('REGALO', 'LOGISTICA', 'FABRICA', 'MARGEN', 'URGENCIA')
MESES = ['', 'ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO', 'JULIO', 'AGOSTO',
         'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE']
DIAS = ['LUNES', 'MARTES', 'MIÉRCOLES', 'JUEVES', 'VIERNES', 'SÁBADO', 'DOMINGO']
DIAS_MIN = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
DIAS_ABR = ['LUN', 'MAR', 'MIÉ', 'JUE', 'VIE', 'SÁB', 'DOM']

COPY_HOOK = {
    'REGALO': "🧴 Armá {promo_copy} y te lo regalamos.",
    'LOGISTICA': "🚚 No tenés que venir a Río Cuarto: el camión te lo deja en el negocio.",
    'FABRICA': "🏭 Somos fábrica, 20 años en Río Cuarto: comprás sin intermediarios.",
    'MARGEN': "💰 Comprás a granel en bidones de 20 L, fraccionás y ganás por litro.",
    'URGENCIA': "⏰ Últimos lugares en el camión: la preventa cierra el {cierre_dia} a las 18 h.",
}


class CristalAgentCreative(models.Model):
    _name = 'cristal.agent.creative'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Pauta Cristal — Creativo"
    _order = 'departure_date desc, zone, angle'

    name = fields.Char(string="Nombre en Meta", required=True,
                       help="[ZONA] ÁNGULO | formato vN | salida DD/MM")
    zone = fields.Char(string="Zona", index=True, help="RUTA-NORTE, RUTA-ESTE, RC, CF…")
    circuit_id = fields.Many2one('cristal.agent.circuit', string="Circuito")
    departure_id = fields.Many2one('cristal.agent.route.departure', string="Salida",
                                   ondelete='set null', index=True)
    departure_date = fields.Date(related='departure_id.date', store=True, string="Fecha de salida")
    angle = fields.Selection(ANGLE_SELECTION, string="Ángulo", required=True, index=True)
    format = fields.Selection(FORMAT_SELECTION, string="Formato", required=True, default='placa')
    version = fields.Integer(string="Versión", default=1)
    attachment_id = fields.Many2one('ir.attachment', string="Archivo", ondelete='set null')
    public_url = fields.Char(string="URL pública", compute='_compute_public_url')
    body = fields.Text(string="Texto del anuncio (copy)")
    headline = fields.Char(string="Título del anuncio")
    script = fields.Text(string="Guion (video)")
    meta_image_hash = fields.Char(string="Meta image hash")
    meta_video_id = fields.Char(string="Meta video id")
    meta_creative_id = fields.Char(string="Meta creative id")
    meta_ad_id = fields.Char(string="Meta ad id")
    state = fields.Selection([
        ('generated', 'Generado'),
        ('in_meta', 'Cargado en Meta'),
        ('draft_ad', 'Anuncio en borrador'),
        ('active', 'Activo'),
        ('paused', 'Pausado'),
        ('scheduled', 'Programado en Metricool'),
        ('done', 'Terminado'),
    ], string="Estado", default='generated', index=True)
    activate_on = fields.Date(string="Activar el", help="URGENCIA: D-2 de la salida.")
    planned_date = fields.Date(string="Publicar el", index=True,
                               help="Orgánico: fecha del posteo en Instagram/Facebook.")
    metricool_id = fields.Char(string="Metricool id", copy=False)
    # Resultados (los completa el analista semanal a D+7)
    spend = fields.Float(string="Gasto", digits=(12, 0))
    conversations = fields.Integer(string="Conversaciones")
    cost_per_conversation = fields.Float(string="Costo por conversación", digits=(12, 0))
    orders = fields.Integer(string="Pedidos atribuidos")
    cpa_real = fields.Float(string="CPA real (Odoo)", digits=(12, 0))
    results_date = fields.Date(string="Resultados al")
    notes = fields.Text(string="Notas")

    @api.depends('attachment_id')
    def _compute_public_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        for rec in self:
            rec.public_url = (f"{base}/website/image/ir.attachment/{rec.attachment_id.id}/datas"
                              if rec.attachment_id else False)


class CristalAgentExperiment(models.Model):
    _name = 'cristal.agent.experiment'
    _description = "Pauta Cristal — Experimento"
    _order = 'date desc, id desc'

    name = fields.Char(string="Hipótesis", required=True)
    date = fields.Date(string="Fecha", default=fields.Date.today, required=True)
    action = fields.Text(string="Acción ejecutada")
    metric = fields.Char(string="Métrica", help="costo por conversación, CPA real, pedidos…")
    value_before = fields.Float(string="Antes", digits=(12, 2))
    value_after = fields.Float(string="Después", digits=(12, 2))
    evaluate_on = fields.Date(string="Evaluar el")
    verdict = fields.Selection([('pending', 'Pendiente'), ('win', 'Funcionó'),
                                ('lose', 'No funcionó'), ('neutral', 'Sin diferencia')],
                               string="Veredicto", default='pending', index=True)
    creative_ids = fields.Many2many('cristal.agent.creative', string="Creativos")
    notes = fields.Text(string="Aprendizaje")


class CristalAgentPauta(models.AbstractModel):
    _name = 'cristal.agent.pauta'
    _description = "Pauta Cristal — contenido automático por salida"

    # ───────────────────────── v1.61.3 — Fotos REALES de los productos ─────────────────────────
    # Joaco (10/11/2026): "las fotos que las saque de la variante de ese producto, se ven feas,
    # muy IA" (etiquetas inventadas, bidones "CRISTAL" que no existen). Las placas se arman con
    # la foto de la variante en Odoo (o la de su producto si la variante no tiene propia).

    @api.model
    def _product_photo(self, product):
        import base64
        raw = product.image_1024 or product.product_tmpl_id.image_1024
        if not raw:
            return None
        try:
            return base64.b64decode(raw)
        except Exception:  # noqa: BLE001
            return None

    @api.model
    def _top_products(self, limit=12):
        """Los más vendidos del catálogo mayorista en 120 días que tienen foto, uno por producto
        (no tres tamaños del mismo jabón)."""
        since = fields.Datetime.now() - timedelta(days=120)
        rows = self.env['sale.order.line'].sudo()._read_group(
            [('order_id.state', 'in', ('sale', 'done')), ('order_id.date_order', '>=', since),
             ('product_id.sale_ok', '=', True), ('product_id.type', '!=', 'combo'),
             ('product_id.product_tmpl_id.is_mayorista_catalog', '=', True)],
            ['product_id'], ['product_uom_qty:sum'])
        rows = sorted(rows, key=lambda r: -(r[1] or 0))
        result, seen, resale = [], set(), []
        for product, _qty in rows:
            tmpl = product.product_tmpl_id
            if tmpl.id in seen or not (product.image_1024 or tmpl.image_1024):
                continue
            seen.add(tmpl.id)
            # Lo de reventa (categoría "Distribución": papel, bolsas, trapos de otras marcas) no
            # va en placas que dicen "fabricamos / precio de fábrica": solo si faltan productos.
            if (tmpl.categ_id.complete_name or '').startswith('Distribuci'):
                resale.append(product)
                continue
            result.append(product)
            if len(result) >= limit:
                break
        return (result + resale)[:limit] if len(result) < 4 else result

    @api.model
    def _pauta_photos(self, angle=None, offer=None, seed=0, n=5):
        """Lo que va en la placa. v1.62.3: si son productos A GRANEL devuelve etiquetas
        [('GRANEL', 'Suavizante'), ('ITEM', 'Base limpiador 1 L'), ...] y la placa muestra
        bidones de 20 L limpios + tarjeta con la lista (las fotos de las variantes son del bidón
        de 5 L y confunden). Si no, fotos (bytes) de los productos de la oferta o de los más
        vendidos, rotando según `seed`."""
        is_granel = lambda p: 'granel' in (p.name or '').lower()  # noqa: E731
        if offer and offer.product_ids:
            products = list(offer.product_ids)
            if any(is_granel(p) for p in products):
                return [('GRANEL', self._granel_label(p)) if is_granel(p)
                        else ('ITEM', self._item_label(p)) for p in products]
        else:
            top = self._top_products()
            labels = list(dict.fromkeys(self._granel_label(p) for p in top if is_granel(p)))
            if len(labels) >= 3:
                start = seed % len(labels)
                return [('GRANEL', x) for x in (labels[start:] + labels[:start])[:6]]
            products = []
            if top:
                start = seed % len(top)
                products = (top[start:] + top[:start])[:n]
        return [p for p in (self._product_photo(prod) for prod in products[:8]) if p]


    _GRANEL_LABELS = (('jabon', 'Jabón líquido'), ('jabón', 'Jabón líquido'),
                      ('suavizante', 'Suavizante'), ('lavandina', 'Lavandina'),
                      ('cloro', 'Cloro'), ('detergente', 'Detergente'),
                      ('desengrasante', 'Desengrasante'), ('limpiador', 'Limpiador'),
                      ('desodorante', 'Desodorante'), ('alcohol', 'Alcohol'))

    @api.model
    def _item_label(self, product):
        """Nombre corto para la lista de la placa: 'Base Limpiador Desodorante (1+80) 1 lt' →
        'Base limpiador 1 L'."""
        import re
        name = re.sub(r'^\[[^\]]*\]\s*', '', product.name or '')
        name = re.sub(r'\([^)]*\)|\bCrilimp\b', ' ', name)
        words = name.split()[:2]
        m = re.search(r'(\d+(?:[.,]\d+)?)\s*(lts?|l|kg|gr?)\b', product.display_name or '', re.I)
        unit = {'l': 'L', 'k': 'kg', 'g': 'g'}.get(m.group(2)[0].lower(), '') if m else ''
        size = f" {m.group(1)} {unit}" if m else ''
        return (' '.join(words).capitalize() + size)[:24]

    @api.model
    def _granel_label(self, product):
        name = (product.name or '').lower()
        for key, label in self._GRANEL_LABELS:
            if key in name:
                return label
        return ' '.join((product.name or '').replace('a granel', '').split()[:2])

    @api.model
    def _scene_for(self, angle, seed=0):
        """Escenario (fondo sin productos) para una placa mayorista."""
        if angle == 'PRODUCTO':
            return 'almacen'
        return ('deposito', 'almacen')[seed % 2]

    @api.model
    def _cf_scene(self, name):
        """Escenario para un combo de la casa según lo que trae."""
        import re
        n = (name or '').lower()
        for pat, scene in ((r'pileta|cloro', 'pileta'), (r'ropa|lavader', 'lavadero'),
                           (r'barrido|mopa|secador|casa limpia', 'bano'), (r'cocina', 'cocina')):
            if re.search(pat, n):
                return scene
        return 'cocina'

    @api.model
    def _short_label(self, product):
        """'Lavandina Doble Rend Crilimp (5 lts)' → 'Lavandina Doble Rend 5 lts'."""
        import re
        name = re.sub(r'^\[[^\]]*\]\s*', '', product.display_name or '')
        name = re.sub(r'\bCrilimp\b\s*', '', name)
        m = re.search(r'\(([^)]*)\)\s*$', name)
        base = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
        if m:
            parts = [x.strip() for x in m.group(1).split(',')]
            size = [x for x in parts if re.search(r'\d', x)]
            base = f"{base} {size[-1]}" if size else base
        return base[:34]

    @api.model
    def generate_cf_combo_placas(self):
        """Placas de los combos para la casa con las fotos reales de lo que trae cada uno (feed
        1080×1350 y story 1080×1920). Una por combo y formato; se reemplaza la anterior. La
        rutina de contenidos de consumidor final las busca por nombre:
        placa_cf_<variante>_feed.jpg / placa_cf_<variante>_story.jpg. Devuelve {nombre: id}."""
        from ..services import cf_combos, placa
        Att = self.env['ir.attachment'].sudo()
        result = {}
        for c in cf_combos.catalog(self.env):
            combo = c['product']
            items, _missing, _chosen = cf_combos.pick_items(combo)
            photos = [(self._short_label(it.product_id), self._product_photo(it.product_id))
                      for it in items]
            photos = [(lab, ph) for lab, ph in photos if ph]
            if not photos:
                continue
            trae = ', '.join(self._short_label(it.product_id) for it in items)
            for fmt, story in (('feed', False), ('story', True)):
                try:
                    data = placa.render_combo(c['name'], c['price'], photos, loose=c['loose'], story=story,
                                              scene=self._cf_scene(c['name']))
                except Exception as e:  # noqa: BLE001
                    _logger.exception("Placa CF %s %s falló: %s", c['name'], fmt, e)
                    continue
                name = f"placa_cf_{combo.id}_{fmt}.jpg"
                Att.search([('name', '=', name), ('res_model', '=', 'product.product')]).unlink()
                att = Att.create({
                    'name': name, 'raw': data, 'mimetype': 'image/jpeg', 'public': True,
                    'res_model': 'product.product', 'res_id': combo.id,
                    'description': (f"Placa CF {c['name']} · {fmt} · fotos reales · Pauta Cristal\n"
                                    f"PRECIO: {round(c['price'])}\nSUELTO: {round(c['loose'])}\n"
                                    f"AHORRO: {round(c['saving'])}\nTRAE: {trae}\n"
                                    f"SIN_STOCK: {', '.join(c['missing']) or '-'}")})
                result[name] = att.id
        return result

    @api.model
    def cron_cf_combo_placas(self):
        """Todos los lunes antes de la rutina de contenidos: placas de combos con precio y
        stock del día."""
        return bool(self.generate_cf_combo_placas())

    @api.model
    def regenerate_future_images(self, from_day=None):
        """Atajo por RPC (v1.61.3): rearma con fotos reales las placas orgánicas e historias
        con fecha desde `from_day` (incluido) y una tanda nueva de Río Cuarto. Borra los
        creativos viejos de esas fechas (y sus adjuntos) y los vuelve a generar con el mismo
        calendario. Devuelve {fecha: url pública} para reprogramar en Metricool."""
        day = fields.Date.to_date(from_day) if from_day else fields.Date.context_today(self)
        Creative = self.env['cristal.agent.creative'].sudo()
        old = Creative.search([('format', 'in', ('organico', 'story')), ('planned_date', '>=', day)])
        months = sorted({d.replace(day=1) for d in old.mapped('planned_date')})
        old.mapped('attachment_id').unlink()
        old.unlink()
        created = Creative.browse()
        for ms in months:
            created |= self.generate_organic_month(ms)
            created |= Creative.browse(self.generate_stories_for(ms, from_day=day))
        created |= self.generate_rc_batch(day)
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return {f"{c.format}|{c.planned_date or ''}|{c.angle}":
                f"{base}/web/content/{c.attachment_id.id}/{c.attachment_id.name}"
                for c in created if c.attachment_id}

    # ───────────────────────── Contexto de una salida ─────────────────────────
    @api.model
    def route_context(self, departure, config=None):
        """Textos de la salida para placas, copys y guion."""
        config = config or self.env['cristal.agent.config'].sudo().get_active()
        d = departure.date
        towns = [t.name for t in departure.circuit_id.town_ids.sorted(
            lambda t: (bool(t.optional), t.id))]
        main = [t for t in towns][:6]
        half = (len(towns) + 1) // 2
        pueblos = ' · '.join(towns[:half]) + ('|' + ' · '.join(towns[half:]) if towns[half:] else '')
        cutoff = d - timedelta(days=1)
        promo_n = int(getattr(config, 'pauta_route_promo_qty', 7) or 7)
        free_from = float(getattr(config, 'pauta_route_free_from', 0.0) or
                          getattr(config, 'route_free_shipping_from', 0.0) or 150000.0)
        pack_from = float(getattr(config, 'pauta_route_pack_from', 0.0) or 170000.0)
        fmt_ars = lambda v: f"${v:,.0f}".replace(',', '.')  # noqa: E731
        return {
            'zone': f"RUTA-{(departure.circuit_id.name or '').upper().replace(' ', '-')}",
            'towns': towns, 'main_towns': main, 'pueblos': pueblos,
            'date': d, 'cutoff': cutoff,
            'dia': f"{DIAS[d.weekday()]} {d.day} DE {MESES[d.month]}",
            'dia_corto': f"{DIAS[d.weekday()]} {d.day}",
            'dia_min': f"{DIAS_MIN[d.weekday()]} {d.day}/{d.month}",
            'cierre_dia': f"{DIAS_MIN[cutoff.weekday()]} {cutoff.day}/{cutoff.month}",
            'dia_urgencia': f"CIERRA EL {DIAS[cutoff.weekday()]} {cutoff.day} A LAS 18 H",
            'promo_l1': f"{promo_n} BIDONES DE 20 L", 'promo_l2': "+ 1 DE REGALO",
            'promo_corta': f"{promo_n} bidones de 20 L + 1 de regalo",
            'promo_copy': f"{promo_n} bidones de 20 L (jabón, suavizante, lavandina, cloro, "
                          f"detergente o desengrasante), mezclados como quieras, y el "
                          f"{promo_n + 1}.º",
            'envio': f"Envío gratis desde {fmt_ars(free_from)}",
            'condiciones': f"Envío gratis desde {fmt_ars(free_from)} · Pack de regalo desde {fmt_ars(pack_from)}",
            'cierre': f"PEDÍ POR WHATSAPP · HASTA EL {DIAS_ABR[cutoff.weekday()]} {cutoff.day}, 18 H",
            'cierre_urgencia': "PEDÍ AHORA POR WHATSAPP",
            'free_from': free_from, 'pack_from': pack_from, 'promo_n': promo_n,
        }

    @api.model
    def copy_for(self, angle, ctx):
        t = ctx['main_towns']
        towns = t[0] if len(t) == 1 else (', '.join(t[:-1]) + ' o ' + t[-1] if t else 'tu zona')
        hook = COPY_HOOK.get(angle, COPY_HOOK['REGALO']).format(**ctx)
        body = (f"🚚 ¿Sos de {towns} o de esa zona y vendés productos de limpieza? "
                f"El {ctx['dia_min'].upper()} el camión de Química Cristal llega a tu negocio.\n\n"
                f"{hook}\n📦 {ctx['condiciones']}.\n"
                f"⏰ Pedidos hasta el {ctx['cierre_dia']} a las 18 h.\n\n"
                f"Escribinos por WhatsApp y te lo dejamos cargado para el camión 👇")
        headline = {
            'REGALO': f"{ctx['promo_corta']} · El camión pasa el {ctx['dia_min']}",
            'LOGISTICA': f"Te lo dejamos en tu negocio · {ctx['dia_min']}",
            'FABRICA': f"Precio de fábrica en tu pueblo · {ctx['dia_min']}",
            'MARGEN': f"Comprás a granel y ganás por litro · {ctx['dia_min']}",
            'URGENCIA': f"Cierra el {ctx['cierre_dia']} a las 18 h · últimos lugares",
        }.get(angle, '')
        return body, headline

    @api.model
    def script_for(self, ctx):
        t = ctx['main_towns']
        return (f"0-3 s · \"¿Tenés un negocio en {', '.join(t[:5])}?\"\n"
                f"3-10 s · \"El {ctx['dia_min']} el camión de Química Cristal pasa por tu pueblo. "
                f"Somos fábrica, en Río Cuarto, hace más de 20 años.\"\n"
                f"10-19 s · \"Armás {ctx['promo_n']} bidones de 20 litros, mezclados como quieras: jabón, "
                f"suavizante, lavandina, cloro, detergente o desengrasante… y el {ctx['promo_n'] + 1}.º te lo "
                f"regalamos. Desde {ctx['envio'].split('desde ')[1]} el envío es sin cargo.\"\n"
                f"19-25 s · \"Pedilo por WhatsApp hasta el {ctx['cierre_dia']} a las 18 y te lo dejamos cargado "
                f"para el camión. Tocá el botón y escribinos.\"")

    # ───────────────────────── Generación ─────────────────────────
    @api.model
    def generate_route_content(self, departure, angles=ROUTE_ANGLES, config=None):
        """Placas + copys + guion para una salida. Idempotente: si ya hay creativos de
        placa para esa salida y ángulo, no los repite. Devuelve los creativos creados."""
        from ..services import placa
        config = config or self.env['cristal.agent.config'].sudo().get_active()
        Creative = self.env['cristal.agent.creative'].sudo()
        Att = self.env['ir.attachment'].sudo()
        ctx = self.route_context(departure, config)
        created = Creative.browse()
        for angle in angles:
            if Creative.search_count([('departure_id', '=', departure.id), ('angle', '=', angle),
                                      ('format', '=', 'placa')]):
                continue
            try:
                data = placa.render_angle(angle, ctx, products=self._pauta_photos(
                    angle, seed=departure.id + ROUTE_ANGLES.index(angle) if angle in ROUTE_ANGLES else departure.id),
                    scene=self._scene_for(angle, departure.id + len(angle)))
            except Exception as e:  # noqa: BLE001
                _logger.exception("Placa %s de %s falló: %s", angle, departure.name, e)
                continue
            fname = f"placa_{ctx['zone'].lower()}_{departure.date:%Y%m%d}_{angle.lower()}_v1.jpg"
            body, headline = self.copy_for(angle, ctx)
            # v1.59: el copy viaja también en la descripción del adjunto (ir.attachment sí está
            # expuesto al conector), así la rutina de campañas por salida lo lee sin otro permiso.
            att = Att.create({'name': fname, 'raw': data, 'mimetype': 'image/jpeg', 'public': True,
                              'res_model': 'cristal.agent.route.departure', 'res_id': departure.id,
                              'description': (f"Placa {angle} · {departure.name} · Pauta Cristal\n"
                                              f"TITULO: {headline}\nTEXTO:\n{body}")})
            vals = {
                'name': f"[{ctx['zone']}] {angle} | placa v1 | salida {departure.date:%d/%m}",
                'zone': ctx['zone'], 'circuit_id': departure.circuit_id.id,
                'departure_id': departure.id, 'angle': angle, 'format': 'placa', 'version': 1,
                'attachment_id': att.id, 'body': body, 'headline': headline,
                'script': self.script_for(ctx) if angle == 'REGALO' else False,
                'state': 'generated',
                'activate_on': departure.date - timedelta(days=2) if angle == 'URGENCIA' else False,
            }
            created |= Creative.create(vals)
        return created

    @api.model
    def generate_for_departure(self, departure_id):
        """Atajo por RPC: genera el contenido de una salida por id (idempotente)."""
        dep = self.env['cristal.agent.route.departure'].sudo().browse(int(departure_id)).exists()
        return self.generate_route_content(dep).ids if dep else []

    @api.model
    def cron_route_content(self):
        """Todos los días: contenido para las salidas que están a ≤ 7 días y todavía no lo
        tienen. Avisa en el canal interno y le agenda a Joaco el video."""
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config or not getattr(config, 'pauta_enabled', False):
            _logger.info("cron_route_content: pauta apagada")
            return False
        today = fields.Date.context_today(config)
        lead = int(getattr(config, 'pauta_route_lead_days', 7) or 7)
        Dep = self.env['cristal.agent.route.departure'].sudo()
        deps = Dep.search([('date', '>', today), ('date', '<=', today + timedelta(days=lead)),
                           ('state', 'in', ('preventa', 'rescate'))])
        Creative = self.env['cristal.agent.creative'].sudo()
        for dep in deps:
            if Creative.search_count([('departure_id', '=', dep.id), ('format', '=', 'placa')]):
                continue
            created = self.generate_route_content(dep, config=config)
            if not created:
                continue
            from markupsafe import Markup, escape
            lines = Markup('').join(
                Markup("<li>%s: <a href='%s'>%s</a></li>") % (c.angle, c.public_url, c.attachment_id.name)
                for c in created)
            html = (Markup("<p>🎨 <b>Contenido listo para la ruta %s del %s</b> (%s placas por ángulo, "
                           "copys y guion).</p><ul>%s</ul><p>La rutina semanal de pauta arma la campaña "
                           "con esto. Falta el video a cámara: guion en el creativo REGALO.</p>")
                    % (escape(dep.circuit_id.name or ''), f"{dep.date:%d/%m}", len(created), lines))
            try:
                if config.internal_channel_id:
                    config.internal_channel_id.sudo().with_context(from_cristal_agent=True).message_post(
                        body=html, message_type='comment', subtype_xmlid='mail.mt_comment')
            except Exception as e:  # noqa: BLE001
                _logger.warning("Aviso de contenido al canal falló: %s", e)
            try:
                user = config.lifecycle_visit_user_id or self.env.ref('base.user_admin')
                regalo = created.filtered(lambda c: c.angle == 'REGALO')[:1] or created[:1]
                regalo.activity_schedule(
                    'mail.mail_activity_data_todo', date_deadline=today + timedelta(days=2),
                    user_id=user.id, summary=f"Video de ruta {dep.circuit_id.name} {dep.date:%d/%m}",
                    note=("Grabar el video a cámara (25 s) con el guion de este creativo, o "
                          "generarlo con Higgsfield si hay saldo (docs/guion-video-ruta.md)."))
            except Exception as e:  # noqa: BLE001
                _logger.warning("Actividad de video falló: %s", e)
        return True

    # ───────────────────────── v1.59 — Orgánico mensual (E5) ─────────────────────────
    @api.model
    def _month_bounds(self, month_start):
        ms = fields.Date.to_date(month_start).replace(day=1)
        nxt = (ms + timedelta(days=32)).replace(day=1)
        return ms, nxt

    @api.model
    def _organic_dates(self, month_start):
        ms, nxt = self._month_bounds(month_start)
        days = (nxt - ms).days
        return [ms + timedelta(days=i) for i in range(days)
                if (ms + timedelta(days=i)).weekday() in ORGANIC_WEEKDAYS
                and ((ms + timedelta(days=i)).month, (ms + timedelta(days=i)).day) not in ORGANIC_SKIP]

    @api.model
    def _organic_offers(self, ref_date):
        """Combos de mayorista vigentes (las promos de consumidor final no van al orgánico
        mayorista)."""
        import re
        from types import SimpleNamespace
        # v1.61.3 — Si el Combo Emprendedor está activo, es EL combo del orgánico (Joaco se quejó
        # de los "Combo Almacén / Kiosco" con "1 caja de…"): lo que trae sale de la config.
        config = self.env['cristal.agent.config'].sudo().get_active()
        lines = config.combo_emprendedor_line_ids.filtered('product_id') if config else []
        if config and getattr(config, 'combo_emprendedor_active', False) and lines:
            items = ', '.join(f"{ln.qty:g} {ln.product_id.uom_id.name or ''} de "
                              f"{self._short_label(ln.product_id)}".replace(' Units de', ' de')
                              for ln in lines)
            return [SimpleNamespace(
                id=0, name=config.combo_emprendedor_name or 'Combo Emprendedor',
                description=f"Para arrancar o reponer tu negocio: {items}. Todo a granel, con bidones de recambio.",
                product_ids=lines.mapped('product_id'))]
        offers = self.env['cristal.agent.offer'].sudo().search(
            [('active', '=', True), ('offer_type', '=', 'bundle')], order='priority desc, id')
        cf = re.compile(r'\bCF\b|consumidor', re.I)
        return offers.filtered(lambda o: (not o.valid_until or o.valid_until >= ref_date)
                               and not cf.search(o.name or '')
                               and '1 caja de' not in (o.description or ''))

    @api.model
    def _organic_buyers(self):
        """Negocios mayoristas que compraron alguna vez (número real para PRUEBA_SOCIAL)."""
        may = self.env['res.partner.category'].sudo().search([('name', '=', 'Mayorista')], limit=1)
        if not may:
            return 0
        groups = self.env['sale.order'].sudo()._read_group(
            [('partner_id.commercial_partner_id.category_id', 'in', may.ids),
             ('state', 'in', ('sale', 'done'))], ['partner_id'])
        return len({p.commercial_partner_id.id for p, in groups})

    @api.model
    def _organic_departures(self, month_start):
        """Salidas del mes: las cargadas, y para los circuitos sin salida cargada, la fecha
        que les toca por la rotación (cada N semanas desde la primera salida)."""
        ms, nxt = self._month_bounds(month_start)
        Dep = self.env['cristal.agent.route.departure'].sudo()
        circuits = self.env['cristal.agent.circuit'].sudo().search([('active', '=', True)])
        out = {}
        for d in Dep.search([('date', '>=', ms), ('date', '<', nxt), ('state', '!=', 'postergada'),
                             ('circuit_id', 'in', circuits.ids)]):
            out[(d.circuit_id.id, d.date)] = (d.date, d.circuit_id.name)
        period = 28  # misma rotación que route.departure.generate_upcoming
        for c in circuits:
            if any(k[0] == c.id for k in out) or not c.first_departure_date:
                continue
            d = c.first_departure_date
            while d < ms:
                d += timedelta(days=period)
            while d < nxt:
                out[(c.id, d)] = (d, c.name)
                d += timedelta(days=period)
        return sorted(out.values())

    @staticmethod
    def _two_lines(text, max_chars=20):
        words = (text or '').split()
        if len(' '.join(words)) <= max_chars or len(words) < 2:
            return ' '.join(words)
        best = None
        for i in range(1, len(words)):
            a, b = ' '.join(words[:i]), ' '.join(words[i:])
            score = max(len(a), len(b))
            if best is None or score < best[0]:
                best = (score, a, b)
        return f"{best[1]}|{best[2]}"

    @api.model
    def organic_spec(self, angle, ctx, offer=None):
        """Textos de la placa (para services/placa.render) y del posteo de un ángulo.
        Devuelve (ángulo efectivo, spec, texto del posteo)."""
        cierre = 'ESCRIBINOS POR WHATSAPP'
        if angle == 'LOGISTICA':
            sal = ctx['salidas']
            half = (len(sal) + 1) // 2
            pueblos = ' · '.join(s[0] for s in sal[:half]) + (
                '|' + ' · '.join(s[0] for s in sal[half:]) if sal[half:] else '')
            titulo = ('EL CAMIÓN SALE|TODOS LOS JUEVES' if ctx.get('solo_jueves', True)
                      else 'EL CAMIÓN SALE|CADA SEMANA')
            spec = dict(base='joaco_camion', dia=f"SALIDAS DE {ctx['mes']}",
                        titulo=titulo, pueblos=pueblos,
                        promo='TE LO DEJAMOS|EN TU NEGOCIO',
                        detalle='Pueblos de la zona, hasta 120 km de Río Cuarto',
                        condiciones='Pedidos hasta el miércoles a las 18 h', cierre=cierre)
            body = (f"🚚 En {ctx['mes_min']} el camión de Química Cristal sale "
                    f"{'todos los jueves' if ctx.get('solo_jueves', True) else 'cada semana'}:\n"
                    + '\n'.join(f"• {s[1]}" for s in sal)
                    + "\n\nSi tenés un negocio en la zona, pedís por WhatsApp hasta el miércoles "
                      "a las 18 h y te lo dejamos en el local 👇")
        elif angle == 'PRUEBA_SOCIAL':
            n = ctx['clientes']
            spec = dict(base='camion_cargado', dia='CLIENTES DE QUÍMICA CRISTAL',
                        titulo=f"+{n} NEGOCIOS|YA NOS COMPRAN", pueblos='',
                        promo='DIRECTO DE FÁBRICA|A TU LOCAL',
                        detalle='Almacenes, kioscos, lavaderos y revendedores de la zona',
                        condiciones='Bidones de 20 L a precio de fábrica', cierre=cierre)
            body = (f"🤝 Más de {n} negocios de Río Cuarto y la zona ya compran directo de "
                    "fábrica en Química Cristal: almacenes, kioscos, lavaderos y revendedores.\n\n"
                    "Precio de fábrica, bidones de 20 L y te lo llevamos al negocio.\n\n"
                    "¿Querés la lista de precios? Escribinos por WhatsApp 👇")
        elif angle == 'PRODUCTO' and offer:
            import re
            # Solo la primera oración es pública: el resto de la descripción de la oferta
            # trae instrucciones internas para Claudio (precio, a quién ofrecerla, etc.).
            desc = ' '.join((offer.description or '').split())
            desc = re.split(r'\.\s', desc)[0].rstrip('.') + '.' if desc else ''
            short = desc.split(':')[0] if ':' in desc[:70] else desc
            short = short if len(short) <= 60 else short[:57].rsplit(' ', 1)[0] + '…'
            spec = dict(base='pallet_regalo', dia=f"COMBO DE {ctx['mes']}",
                        titulo=self._two_lines((offer.name or 'Combo del mes').upper()),
                        pueblos='', promo='ARMADO PARA|TU NEGOCIO', detalle=short,
                        condiciones='Precio de fábrica · pedilo por WhatsApp', cierre=cierre)
            body = (f"🎁 {offer.name}\n\n{desc}\n\n"
                    "Lo armamos para tu negocio a precio de fábrica. Pedilo por WhatsApp 👇")
        elif angle == 'MARGEN':
            spec = dict(base='camion_cargado', dia='PARA REVENDEDORES',
                        titulo='COMPRÁS A GRANEL|GANÁS POR LITRO', pueblos='',
                        promo='FRACCIONÁS|Y REVENDÉS',
                        detalle='Bidones de 20 L a precio de fábrica, directo al negocio',
                        condiciones='Jabón, suavizante, lavandina, cloro, detergente', cierre=cierre)
            body = ("💰 Comprás a granel en bidones de 20 L, fraccionás en tu local y ganás por "
                    "litro.\n\nJabón líquido, suavizante, lavandina, cloro, detergente y "
                    "desengrasante, hechos en nuestra fábrica de Río Cuarto.\n\n"
                    "Pedí la lista de precios por WhatsApp 👇")
        else:  # FABRICA (y PRODUCTO sin oferta)
            angle = 'FABRICA'
            spec = dict(base='joaco_deposito', dia='FÁBRICA EN RÍO CUARTO',
                        titulo='SOMOS FÁBRICA|SIN INTERMEDIARIOS', pueblos='',
                        promo='PRECIO DE FÁBRICA|PARA TU NEGOCIO',
                        detalle='Jabón, suavizante, lavandina, cloro, detergente y desengrasante',
                        condiciones='Bidones de 20 L · lista de precios por WhatsApp', cierre=cierre)
            body = ("🏭 Somos fábrica: hacemos nuestros productos en Río Cuarto hace más de 20 "
                    "años.\n\nSi tenés un almacén, kiosco, lavadero o revendés productos de "
                    "limpieza, comprás directo y sin intermediarios.\n\n"
                    "Escribinos por WhatsApp y te pasamos la lista de precios 👇")
        return angle, spec, f"{body}\n\n{ORGANIC_HASHTAGS}"

    @api.model
    def generate_organic_month(self, month_start, config=None):
        """Calendario orgánico de un mes: una placa por martes y viernes, rotando ángulos,
        con su texto. Idempotente por fecha. Devuelve los creativos creados."""
        from ..services import placa
        ms, nxt = self._month_bounds(month_start)
        Creative = self.env['cristal.agent.creative'].sudo()
        Att = self.env['ir.attachment'].sudo()
        offers = list(self._organic_offers(ms))
        buyers = (self._organic_buyers() // 10) * 10
        sal = self._organic_departures(ms)
        ctx = {
            'mes': MESES[ms.month], 'mes_min': MESES[ms.month].lower(), 'clientes': buyers,
            'solo_jueves': all(d.weekday() == 3 for d, _n in sal),
            'salidas': [(f"{DIAS_ABR[d.weekday()]} {d.day} {(name or '').upper()}",
                         f"{DIAS_MIN[d.weekday()]} {d.day}/{d.month}: {name}") for d, name in sal],
        }
        created = Creative.browse()
        oi = 0
        for i, day in enumerate(self._organic_dates(ms)):
            angle = ORGANIC_ROTATION[i % len(ORGANIC_ROTATION)]
            offer = None
            if angle == 'PRODUCTO':
                if offers:
                    offer = offers[oi % len(offers)]
                    oi += 1
                else:
                    angle = 'MARGEN' if i % 2 else 'FABRICA'
            if angle == 'PRUEBA_SOCIAL' and buyers < 20:
                angle = 'MARGEN'
            if angle == 'LOGISTICA' and not sal:
                angle = 'FABRICA'
            if Creative.search_count([('format', '=', 'organico'), ('planned_date', '=', day)]):
                continue
            angle, spec, body = self.organic_spec(angle, ctx, offer)
            spec['products'] = self._pauta_photos(angle, offer, seed=day.toordinal())
            spec['scene'] = self._scene_for(angle, day.toordinal())
            try:
                data = placa.render(**spec)
            except Exception as e:  # noqa: BLE001
                _logger.exception("Placa orgánica %s del %s falló: %s", angle, day, e)
                continue
            version = Creative.search_count([('format', '=', 'organico'), ('angle', '=', angle)]) + 1
            att = Att.create({'name': f"organico_{day:%Y%m%d}_{angle.lower()}_v{version}.jpg",
                              'raw': data, 'mimetype': 'image/jpeg', 'public': True,
                              'description': (f"Orgánico {angle} · {day:%d/%m} · Pauta Cristal\n"
                                              f"FECHA: {day:%Y-%m-%d}\nTEXTO:\n{body}")})
            created |= Creative.create({
                'name': f"[ORGANICO] {angle} | placa v{version} | {day:%d/%m}",
                'zone': 'ORGANICO', 'angle': angle, 'format': 'organico', 'version': version,
                'attachment_id': att.id, 'body': body, 'planned_date': day,
                'headline': offer.name if offer else False, 'state': 'generated',
                'notes': f"Oferta: {offer.name} (id {offer.id})" if offer else False,
            })
        config = config or self.env['cristal.agent.config'].sudo().get_active()
        if config and getattr(config, 'pauta_story_enabled', True):
            created |= self.generate_stories_month(ms, ctx, offers, sal)
        return created

    # ───────────────────────── v1.60 — Historias diarias (9:16) ─────────────────────────
    @api.model
    def _week_departure(self, day, sal):
        """Salida del jueves de la semana de `day` (lunes a domingo), si hay: (fecha, circuito)."""
        monday = day - timedelta(days=day.weekday())
        thursday = monday + timedelta(days=3)
        for d, name in sal:
            if d == thursday:
                return d, name
        return None

    @api.model
    def story_spec(self, day, ctx, offer=None, dep=None):
        """Historia del día según el día de la semana. Devuelve (ángulo, spec, texto)."""
        wd = day.weekday()
        cierre = 'ESCRIBINOS POR WHATSAPP'
        if dep and wd in (0, 2, 3):
            d, name = dep
            circuit = self.env['cristal.agent.circuit'].sudo().search([('name', '=', name)], limit=1)
            towns = [t.name for t in circuit.town_ids.sorted(lambda t: (bool(t.optional), t.id))][:8]
            half = (len(towns) + 1) // 2
            pueblos = ' · '.join(towns[:half]) + ('|' + ' · '.join(towns[half:]) if towns[half:] else '')
            cut = d - timedelta(days=1)
            if wd == 0:
                spec = dict(base='joaco_camion', dia=f"ESTE JUEVES {d.day}/{d.month}",
                            titulo=f"EL CAMIÓN VA|A {name.upper()}", pueblos=pueblos,
                            promo='PEDÍ HASTA EL|MIÉRCOLES 18 H', detalle='Te lo dejamos en tu negocio',
                            condiciones='Mezclás los productos como quieras', cierre=cierre)
                body = (f"🚚 Este jueves {d.day}/{d.month} el camión va a {name}: "
                        f"{', '.join(towns)}. Pedidos hasta el miércoles a las 18 h.")
                return 'LOGISTICA', spec, body
            if wd == 2:
                spec = dict(base='joaco_camion', dia=f"HOY {cut.day}/{cut.month} CIERRA",
                            titulo='ÚLTIMO DÍA PARA|SUBIRTE AL CAMIÓN', pueblos=pueblos,
                            promo='CIERRA HOY|A LAS 18 H', detalle=f"Sale mañana a {name}",
                            condiciones='Escribinos y lo dejamos cargado', cierre=cierre)
                body = f"⏰ Hoy a las 18 h cierra la preventa del camión a {name}. Mañana sale."
                return 'URGENCIA', spec, body
            spec = dict(base='camion_cargado', dia=f"HOY {d.day}/{d.month}",
                        titulo=f"SALIMOS PARA|{name.upper()}", pueblos=pueblos,
                        promo='¿TE LO|PERDISTE?', detalle='La próxima pasada es en 4 semanas',
                        condiciones='Escribinos y te anotamos', cierre=cierre)
            body = f"🚚 Hoy sale el camión a {name}. ¿Te lo perdiste? Escribinos y te anotamos para la próxima."
            return 'LOGISTICA', spec, body
        by_wd = {1: 'PRODUCTO', 4: 'FABRICA', 5: 'MARGEN', 6: 'PRUEBA_SOCIAL', 0: 'MARGEN',
                 2: 'PRODUCTO', 3: 'FABRICA'}
        angle = by_wd[wd]
        if angle == 'PRUEBA_SOCIAL' and ctx.get('clientes', 0) < 20:
            angle = 'FABRICA'
        angle, spec, body = self.organic_spec(angle, ctx, offer if angle == 'PRODUCTO' else None)
        body = body.split('\n\n#')[0]
        return angle, spec, body

    @api.model
    def generate_stories_for(self, month_start, from_day=None):
        """Atajo por RPC: historias de un mes (por ejemplo, de un mes cuyo feed ya existía)."""
        ms, _nxt = self._month_bounds(month_start)
        offers = list(self._organic_offers(ms))
        sal = self._organic_departures(ms)
        ctx = {'mes': MESES[ms.month], 'mes_min': MESES[ms.month].lower(),
               'clientes': (self._organic_buyers() // 10) * 10, 'salidas': [], 'solo_jueves': True}
        return self.generate_stories_month(ms, ctx, offers, sal, from_day=from_day).ids

    @api.model
    def generate_rc_now(self):
        """Atajo por RPC: una tanda de placas de Río Cuarto ya."""
        return self.generate_rc_batch().ids

    @api.model
    def generate_stories_month(self, month_start, ctx, offers, sal, from_day=None):
        """Una historia 9:16 por día del mes (menos Navidad y Año Nuevo). Idempotente por fecha."""
        from ..services import placa
        ms, nxt = self._month_bounds(month_start)
        Creative = self.env['cristal.agent.creative'].sudo()
        Att = self.env['ir.attachment'].sudo()
        created = Creative.browse()
        oi = 0
        day = max(ms, fields.Date.to_date(from_day)) if from_day else ms
        while day < nxt:
            if (day.month, day.day) in ORGANIC_SKIP or Creative.search_count(
                    [('format', '=', 'story'), ('planned_date', '=', day)]):
                day += timedelta(days=1)
                continue
            offer = None
            if offers and day.weekday() in (1, 2):
                offer = offers[oi % len(offers)]
                oi += 1
            angle, spec, body = self.story_spec(day, ctx, offer, self._week_departure(day, sal))
            spec['products'] = self._pauta_photos(angle, offer if angle == 'PRODUCTO' else None,
                                                  seed=day.toordinal(), n=6)
            spec['scene'] = self._scene_for(angle, day.toordinal())
            try:
                data = placa.render(story=True, **spec)
            except Exception as e:  # noqa: BLE001
                _logger.exception("Historia %s del %s falló: %s", angle, day, e)
                day += timedelta(days=1)
                continue
            version = Creative.search_count([('format', '=', 'story'), ('angle', '=', angle)]) + 1
            att = Att.create({'name': f"historia_{day:%Y%m%d}_{angle.lower()}_v{version}.jpg",
                              'raw': data, 'mimetype': 'image/jpeg', 'public': True,
                              'description': (f"Historia {angle} · {day:%d/%m} · Pauta Cristal\n"
                                              f"FECHA: {day:%Y-%m-%d}\nTEXTO:\n{body}")})
            created |= Creative.create({
                'name': f"[HISTORIA] {angle} | story v{version} | {day:%d/%m}",
                'zone': 'ORGANICO', 'angle': angle, 'format': 'story', 'version': version,
                'attachment_id': att.id, 'body': body, 'planned_date': day, 'state': 'generated',
            })
            day += timedelta(days=1)
        return created

    # ───────────────────────── v1.60 — Placas de Río Cuarto que rotan ─────────────────────────
    RC_VARIANTS = {
        'FABRICA': [('SOMOS FÁBRICA|SIN INTERMEDIARIOS', 'PRECIO DE FÁBRICA|PARA TU NEGOCIO'),
                    ('HECHO EN|RÍO CUARTO', 'COMPRÁ DIRECTO|A LA FÁBRICA'),
                    ('20 AÑOS|FABRICANDO', 'TU PROVEEDOR|DE LIMPIEZA')],
        'MARGEN': [('COMPRÁS A GRANEL|GANÁS POR LITRO', 'FRACCIONÁS|Y REVENDÉS'),
                   ('MÁS MARGEN|EN CADA LITRO', 'BIDONES DE 20 L|A PRECIO DE FÁBRICA'),
                   ('LO QUE MÁS|SE VENDE', 'EN TU GÓNDOLA|TODO EL AÑO')],
        'PRUEBA_SOCIAL': [('+{n} NEGOCIOS|YA NOS COMPRAN', 'DIRECTO DE FÁBRICA|A TU LOCAL'),
                          ('{n} NEGOCIOS|CONFÍAN EN CRISTAL', 'SUMATE A LOS|QUE YA COMPRAN')],
    }
    RC_HEADLINES = {
        'FABRICA': "Precio de fábrica en Río Cuarto",
        'MARGEN': "Comprás a granel y ganás por litro",
        'PRUEBA_SOCIAL': "Negocios de la zona ya nos compran",
        'PRODUCTO': "Combo armado para tu negocio",
    }

    @api.model
    def generate_rc_batch(self, day=None):
        """Placas nuevas para la campaña continua de Río Cuarto: una por ángulo, sin pueblos,
        con otra foto y otro título que la tanda anterior. Copy en la descripción del adjunto."""
        from ..services import placa
        day = fields.Date.to_date(day) if day else fields.Date.context_today(self)
        Creative = self.env['cristal.agent.creative'].sudo()
        Att = self.env['ir.attachment'].sudo()
        batch = Creative.search_count([('zone', '=', 'RC')]) // 4
        buyers = (self._organic_buyers() // 10) * 10
        offers = list(self._organic_offers(day))
        ctx = {'mes': MESES[day.month], 'mes_min': MESES[day.month].lower(), 'clientes': buyers,
               'salidas': [], 'solo_jueves': True}
        bases = list(BASES_ORDER)
        angles = ['FABRICA', 'MARGEN', 'PRODUCTO'] + (['PRUEBA_SOCIAL'] if buyers >= 20 else [])
        created = Creative.browse()
        for k, angle in enumerate(angles):
            offer = offers[batch % len(offers)] if (angle == 'PRODUCTO' and offers) else None
            real, spec, body = self.organic_spec(angle, ctx, offer)
            variants = self.RC_VARIANTS.get(real)
            if variants:
                tit, pro = variants[batch % len(variants)]
                spec['titulo'], spec['promo'] = tit.format(n=buyers), pro
            spec['base'] = bases[(batch + k) % len(bases)]
            spec['products'] = self._pauta_photos(real, offer, seed=batch * 5 + k)
            spec['scene'] = self._scene_for(real, batch + k)
            spec['dia'] = 'RÍO CUARTO Y LA ZONA'
            body = body.split('\n\n#')[0]
            try:
                data = placa.render(**spec)
            except Exception as e:  # noqa: BLE001
                _logger.exception("Placa RC %s falló: %s", real, e)
                continue
            version = Creative.search_count([('zone', '=', 'RC'), ('angle', '=', real)]) + 1
            headline = self.RC_HEADLINES.get(real, '')
            att = Att.create({'name': f"placa_rc_{day:%Y%m%d}_{real.lower()}_v{version}.jpg",
                              'raw': data, 'mimetype': 'image/jpeg', 'public': True,
                              'description': (f"Placa RC {real} v{version} · Pauta Cristal\n"
                                              f"TITULO: {headline}\nTEXTO:\n{body}")})
            created |= Creative.create({
                'name': f"[RC] {real} | placa v{version} | continuo",
                'zone': 'RC', 'angle': real, 'format': 'placa', 'version': version,
                'attachment_id': att.id, 'body': body, 'headline': headline, 'state': 'generated',
            })
        return created

    @api.model
    def cron_rc_creatives(self):
        """Todos los días: si la última tanda de Río Cuarto tiene `pauta_rc_every_days` días o
        más, genera otra. La rutina semanal las carga en Meta y pausa las que pierden."""
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config or not config.pauta_enabled:
            return False
        every = int(getattr(config, 'pauta_rc_every_days', 14) or 14)
        last = self.env['cristal.agent.creative'].sudo().search(
            [('zone', '=', 'RC')], order='create_date desc', limit=1)
        today = fields.Date.context_today(config)
        if last and (today - last.create_date.date()).days < every:
            return True
        self.generate_rc_batch(today)
        return True

    @api.model
    def cron_organic_content(self, force=False):
        """Todos los días: desde el día `pauta_organic_day` arma el calendario orgánico del
        mes siguiente si todavía no existe, y avisa en el canal interno. La rutina semanal
        de pauta lo sube a Metricool para revisión."""
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config or not config.pauta_enabled or not config.pauta_organic_enabled:
            _logger.info("cron_organic_content: orgánico apagado")
            return False
        today = fields.Date.context_today(config)
        # v1.61: las historias del mes en curso (desde hoy) y, desde el día del orgánico, las del
        # mes siguiente: idempotente, así un mes cuyo feed ya existía también tiene historias.
        if getattr(config, 'pauta_story_enabled', True):
            try:
                self.generate_stories_for(today, from_day=today)
                if force or today.day >= (config.pauta_organic_day or 25):
                    self.generate_stories_for(self._month_bounds(today)[1])
            except Exception as e:  # noqa: BLE001
                _logger.exception("Historias del cron fallaron: %s", e)
        if not force and today.day < (config.pauta_organic_day or 25):
            return False
        ms, nxt = self._month_bounds(today)
        target, after = self._month_bounds(nxt)
        Creative = self.env['cristal.agent.creative'].sudo()
        expected = len(self._organic_dates(target))
        have = Creative.search_count([('format', '=', 'organico'), ('planned_date', '>=', target),
                                      ('planned_date', '<', after)])
        if have >= expected:
            return True
        created = self.generate_organic_month(target, config=config)
        if created and config.internal_channel_id:
            from markupsafe import Markup, escape
            lines = Markup('').join(
                Markup("<li>%s · %s: <a href='%s'>placa</a></li>")
                % (f"{c.planned_date:%d/%m}", c.angle, c.public_url) for c in created)
            html = (Markup("<p>📅 <b>Contenido orgánico de %s listo</b> (%s posteos, martes y "
                           "viernes).</p><ul>%s</ul><p>La rutina semanal los sube a Metricool "
                           "para revisión; nada se publica sin tu OK.</p>")
                    % (escape(MESES[target.month].lower()), len(created), lines))
            try:
                config.internal_channel_id.sudo().with_context(from_cristal_agent=True).message_post(
                    body=html, message_type='comment', subtype_xmlid='mail.mt_comment')
            except Exception as e:  # noqa: BLE001
                _logger.warning("Aviso de orgánico al canal falló: %s", e)
        return True
