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
]
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
        ('done', 'Terminado'),
    ], string="Estado", default='generated', index=True)
    activate_on = fields.Date(string="Activar el", help="URGENCIA: D-2 de la salida.")
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
                data = placa.render_angle(angle, ctx)
            except Exception as e:  # noqa: BLE001
                _logger.exception("Placa %s de %s falló: %s", angle, departure.name, e)
                continue
            fname = f"placa_{ctx['zone'].lower()}_{departure.date:%Y%m%d}_{angle.lower()}_v1.jpg"
            att = Att.create({'name': fname, 'raw': data, 'mimetype': 'image/jpeg', 'public': True,
                              'res_model': 'cristal.agent.route.departure', 'res_id': departure.id,
                              'description': f"Placa {angle} · {departure.name} · Pauta Cristal"})
            body, headline = self.copy_for(angle, ctx)
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
