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
