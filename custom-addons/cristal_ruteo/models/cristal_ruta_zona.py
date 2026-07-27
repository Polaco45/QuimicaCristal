# -*- coding: utf-8 -*-
"""
Ruteo de visitas — Pieza 2: micro-zonas por día (PJP).

Una zona es un objeto real (no una etiqueta suelta): agrupa clientes cercanos
de la cartera de un vendedor y tiene asignado un día de la semana. El sistema
las arma solas por cercanía (k-means puro sobre lat/long) y le da a cada zona
su día, de oeste a este (Lun→Vie), para que la vendedora viaje compacto.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

WEEKDAYS = [
    ('0', 'Lunes'),
    ('1', 'Martes'),
    ('2', 'Miércoles'),
    ('3', 'Jueves'),
    ('4', 'Viernes'),
    ('5', 'Sábado'),
    ('6', 'Domingo'),
]


class CristalRutaZona(models.Model):
    _name = 'cristal.ruta.zona'
    _description = 'Zona de ruteo de visitas'
    _order = 'user_id, sequence, id'

    name = fields.Char(string="Nombre", required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    color = fields.Integer(string="Color")
    user_id = fields.Many2one(
        'res.users', string="Vendedor", index=True,
        help="Vendedor dueño de esta zona / cartera.")
    weekday = fields.Selection(
        WEEKDAYS, string="Día de visita",
        help="Día de la semana en que se recorre esta zona (PJP).")

    partner_ids = fields.One2many('res.partner', 'ruteo_zona_id', string="Clientes")
    partner_count = fields.Integer(compute='_compute_stats', store=True, string="Clientes")
    located_count = fields.Integer(compute='_compute_stats', store=True, string="Ubicados")
    center_latitude = fields.Float(digits=(10, 7), compute='_compute_stats', store=True)
    center_longitude = fields.Float(digits=(10, 7), compute='_compute_stats', store=True)

    @api.depends('partner_ids', 'partner_ids.partner_latitude',
                 'partner_ids.partner_longitude', 'partner_ids.ruteo_is_located')
    def _compute_stats(self):
        for zona in self:
            partners = zona.partner_ids
            located = partners.filtered('ruteo_is_located')
            zona.partner_count = len(partners)
            zona.located_count = len(located)
            if located:
                zona.center_latitude = sum(located.mapped('partner_latitude')) / len(located)
                zona.center_longitude = sum(located.mapped('partner_longitude')) / len(located)
            else:
                zona.center_latitude = 0.0
                zona.center_longitude = 0.0

    def action_view_partners(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Clientes de %s") % self.name,
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('ruteo_zona_id', '=', self.id)],
            'context': {'default_ruteo_zona_id': self.id},
        }

    # ─────────── Clustering geográfico automático ───────────
    @api.model
    def autoassign_zonas(self, user_id, n_zonas=5, reset=True):
        """Agrupa los clientes geolocalizados del vendedor en zonas compactas
        (k-means) y le asigna a cada zona un día de la semana (Lun→Vie, ordenadas
        de oeste a este). Devuelve el recordset de zonas resultante."""
        user = self.env['res.users'].browse(user_id)
        if not user.exists():
            raise UserError(_("Seleccioná un vendedor válido."))

        Partner = self.env['res.partner']
        partners = Partner.search([
            ('user_id', '=', user_id),
            ('ruteo_is_located', '=', True),
        ])
        if not partners:
            raise UserError(_(
                "%s todavía no tiene clientes geolocalizados. Cargá las direcciones "
                "y esperá la geolocalización (Pieza 1) antes de armar las zonas."
            ) % user.name)

        points = [(p.id, p.partner_latitude, p.partner_longitude) for p in partners]
        k = max(1, min(n_zonas, len(points)))
        clusters = self._kmeans(points, k)

        # Ordenar de oeste a este (por longitud del centroide) para el flujo Lun→Vie.
        clusters.sort(key=lambda c: c['center'][1])

        if reset:
            old = self.with_context(active_test=False).search([('user_id', '=', user_id)])
            old.partner_ids.write({'ruteo_zona_id': False})
            old.unlink()

        zonas = self.browse()
        for idx, cluster in enumerate(clusters):
            weekday = str(idx % 5)  # 0..4 = Lunes..Viernes
            weekday_label = dict(WEEKDAYS)[weekday]
            first_name = (user.name or _("Vendedor")).split()[0]
            zona = self.create({
                'name': _("%s — %s") % (first_name, weekday_label),
                'user_id': user_id,
                'weekday': weekday,
                'sequence': idx * 10,
                'color': idx % 11,
            })
            Partner.browse(cluster['ids']).write({'ruteo_zona_id': zona.id})
            zonas |= zona

        _logger.info("🗺️ Ruteo: %s zona(s) armadas para %s (%s clientes ubicados)",
                     len(zonas), user.name, len(points))
        return zonas

    @staticmethod
    def _kmeans(points, k, iterations=30):
        """k-means simple y determinista sobre (lat, lng).

        points: lista de tuplas (partner_id, lat, lng).
        Devuelve lista de dicts {'ids': [...], 'center': (lat, lng)}.
        Init determinista (semillas equiespaciadas al ordenar) para que el
        resultado sea reproducible sin usar random.
        """
        if not points:
            return []
        ordered = sorted(points, key=lambda p: (p[1], p[2]))
        if k <= 1:
            centers = [list(ordered[0][1:])]
        else:
            centers = [
                list(ordered[int(i * (len(ordered) - 1) / (k - 1))][1:])
                for i in range(k)
            ]

        assignment = [0] * len(points)
        for _iteration in range(iterations):
            changed = False
            for i, (_pid, lat, lng) in enumerate(points):
                best, best_dist = 0, None
                for c, (clat, clng) in enumerate(centers):
                    dist = (lat - clat) ** 2 + (lng - clng) ** 2
                    if best_dist is None or dist < best_dist:
                        best, best_dist = c, dist
                if assignment[i] != best:
                    assignment[i] = best
                    changed = True
            for c in range(len(centers)):
                members = [points[i] for i in range(len(points)) if assignment[i] == c]
                if members:
                    centers[c] = [
                        sum(m[1] for m in members) / len(members),
                        sum(m[2] for m in members) / len(members),
                    ]
            if not changed:
                break

        clusters = []
        for c in range(len(centers)):
            ids = [points[i][0] for i in range(len(points)) if assignment[i] == c]
            if ids:
                clusters.append({'ids': ids, 'center': (centers[c][0], centers[c][1])})
        return clusters

    # ─────────── Generador de ruta diaria (Pieza 5) ───────────
    @staticmethod
    def _nearest_neighbor_order(points, start):
        """Ordena los puntos por cercanía (vecino más cercano) desde 'start'.
        points: [(id, lat, lng)]; start: (lat, lng). Devuelve la lista ordenada."""
        remaining = list(points)
        ordered = []
        cur = start
        while remaining:
            nxt = min(remaining, key=lambda p: (p[1] - cur[0]) ** 2 + (p[2] - cur[1]) ** 2)
            ordered.append(nxt)
            cur = (nxt[1], nxt[2])
            remaining.remove(nxt)
        return ordered

    def _ruteo_activity_type(self):
        """Tipo de actividad 'Visitar Institución' (o la primera de categoría reunión)."""
        AT = self.env['mail.activity.type']
        return (AT.search([('name', 'ilike', 'Visitar')], limit=1)
                or AT.search([('category', '=', 'meeting')], limit=1))

    @api.model
    def _cron_generate_daily_routes(self, target_date=None, max_visits=9):
        """Arma la ruta del día: para cada zona cuyo día coincide con la fecha,
        toma los clientes que le tocan, los ordena por prioridad + cercanía y crea
        una actividad 'Visitar Institución' numerada en cada uno."""
        target = target_date or fields.Date.context_today(self)
        weekday = str(fields.Date.from_string(target).weekday())  # Lunes=0
        zonas = self.search([('weekday', '=', weekday)])
        if not zonas:
            return
        Activity = self.env['mail.activity']
        Partner = self.env['res.partner']
        act_type = self._ruteo_activity_type()
        model_id = self.env['ir.model']._get_id('res.partner')

        total = 0
        for zona in zonas:
            located = zona.partner_ids.filtered('ruteo_is_located')
            if not located:
                continue
            due = located.filtered('ruteo_is_due') or located
            scored = due.sorted(key=lambda p: p.ruteo_priority_score, reverse=True)[:max_visits]
            if not scored:
                continue
            pts = [(p.id, p.partner_latitude, p.partner_longitude) for p in scored]
            start = (zona.center_latitude, zona.center_longitude)
            ordered = self._nearest_neighbor_order(pts, start)

            # Limpiar las actividades de ruta previas de esta fecha para estos clientes
            # (regenerar es idempotente; no toca actividades cargadas a mano).
            Activity.search([
                ('ruteo_generated', '=', True),
                ('date_deadline', '=', target),
                ('res_model', '=', 'res.partner'),
                ('res_id', 'in', scored.ids),
            ]).unlink()

            for idx, (pid, _lat, _lng) in enumerate(ordered, start=1):
                partner = Partner.browse(pid)
                type_label = dict(partner._fields['ruteo_visit_type'].selection).get(
                    partner.ruteo_visit_type, '')
                Activity.create({
                    'res_model_id': model_id,
                    'res_id': pid,
                    'activity_type_id': act_type.id if act_type else False,
                    'user_id': zona.user_id.id or self.env.uid,
                    'date_deadline': target,
                    'summary': "Visita #%s · %s" % (idx, type_label),
                    'note': partner._ruteo_visit_reason(),
                    'ruteo_generated': True,
                    'ruteo_sequence': idx,
                })
                total += 1
        _logger.info("🚗 Ruteo: %s visitas generadas para %s", total, target)
        return total

    def _action_generate_today(self):
        """Botón/acción: genera la ruta de hoy y muestra las visitas del día."""
        self._cron_generate_daily_routes()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Mi ruta de hoy"),
            'res_model': 'mail.activity',
            'view_mode': 'list,form',
            'domain': [('ruteo_generated', '=', True),
                       ('date_deadline', '=', fields.Date.context_today(self))],
            'context': {'search_default_ruteo_mias': 1},
        }
