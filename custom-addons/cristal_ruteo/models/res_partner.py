# -*- coding: utf-8 -*-
"""
Ruteo de visitas — Pieza 1: geolocalización automática.

La vendedora carga la dirección de calle del cliente y el sistema lo ubica
solo en el mapa. Estrategia robusta y desacoplada del guardado:

  · Al crear/editar la dirección se marca `ruteo_geo_pending = True` (barato,
    no bloquea el save ni rompe importaciones masivas).
  · Un cron cada ~10 min geolocaliza los pendientes en lote, respetando el
    rate-limit del proveedor (OpenStreetMap/Nominatim: ≤1 req/seg).
  · Hay un botón "Geolocalizar ahora" para ubicar al instante un cliente.

Todo el geocodificado va envuelto en try/except: NUNCA rompe un guardado ni
un cron por un fallo del proveedor.
"""
import logging
import time
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Campos de dirección que, al cambiar, disparan una nueva geolocalización.
ADDRESS_TRIGGER_FIELDS = {'street', 'street2', 'city', 'zip', 'state_id', 'country_id'}

# Frecuencia de visita (días) según el nivel mayorista que calcula cristal_agent.
RUTEO_FREQ_BY_LEVEL = {'oro': 7, 'plata': 15, 'bronce': 30}
# Cadencia de captación para clientes nuevos/prospectos todavía sin nivel.
RUTEO_FREQ_PROSPECT = 15


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ─────────── Estado del geocodificado para el ruteo ───────────
    ruteo_geo_status = fields.Selection([
        ('pending', 'Pendiente de ubicar'),
        ('ok', 'Ubicado'),
        ('failed', 'No se pudo ubicar'),
    ], string="Estado geolocalización", index=True, copy=False,
        help="Estado del geocodificado automático para el ruteo de visitas.")

    ruteo_geo_pending = fields.Boolean(
        string="Geo pendiente", default=False, index=True, copy=False,
        help="Se marca cuando cambió la dirección y falta (re)ubicar en el mapa. "
             "Un cron lo procesa cada pocos minutos.")

    ruteo_geo_last_try = fields.Datetime(string="Último intento de geo", copy=False)
    ruteo_geo_message = fields.Char(string="Detalle geolocalización", copy=False)

    ruteo_is_located = fields.Boolean(
        string="Ubicado en el mapa", compute='_compute_ruteo_is_located', store=True,
        help="Verdadero si tiene coordenadas válidas (no 0,0).")

    # ─────────── Zona de ruteo (Pieza 2) ───────────
    ruteo_zona_id = fields.Many2one(
        'cristal.ruta.zona', string="Zona de ruteo", index=True, ondelete='set null',
        help="Micro-zona geográfica a la que pertenece el cliente. Define en qué "
             "día de la semana lo visita la vendedora (PJP).")
    ruteo_weekday = fields.Selection(
        related='ruteo_zona_id.weekday', string="Día de visita", store=True, index=True)

    # ─────────── Frecuencia y próxima visita (Pieza 3) ───────────
    ruteo_frequency_days = fields.Integer(
        string="Frecuencia de visita (días)", compute='_compute_ruteo_frequency_days',
        store=True,
        help="Cada cuántos días conviene visitar. Deriva del nivel mayorista: "
             "oro=7, plata=15, bronce=30. Nuevos/prospectos = 15 (captación).")
    ruteo_last_visit = fields.Date(
        string="Última visita", copy=False, index=True,
        help="Fecha de la última visita presencial registrada. La setea el cierre "
             "de la actividad de visita.")
    ruteo_next_visit_due = fields.Date(
        string="Próxima visita", compute='_compute_ruteo_next_visit_due', store=True,
        help="Cuándo le toca la próxima visita (última visita + frecuencia). "
             "Vacío = nunca visitado, prioridad de primera visita.")
    ruteo_is_due = fields.Boolean(
        string="Le toca visita", compute='_compute_ruteo_is_due',
        help="Verdadero si ya pasó su fecha de próxima visita o nunca fue visitado.")

    @api.depends('agent_level')
    def _compute_ruteo_frequency_days(self):
        for partner in self:
            partner.ruteo_frequency_days = RUTEO_FREQ_BY_LEVEL.get(
                partner.agent_level, RUTEO_FREQ_PROSPECT)

    @api.depends('ruteo_last_visit', 'ruteo_frequency_days')
    def _compute_ruteo_next_visit_due(self):
        for partner in self:
            if partner.ruteo_last_visit:
                partner.ruteo_next_visit_due = partner.ruteo_last_visit + timedelta(
                    days=partner.ruteo_frequency_days or 0)
            else:
                partner.ruteo_next_visit_due = False

    @api.depends('ruteo_next_visit_due', 'ruteo_last_visit')
    def _compute_ruteo_is_due(self):
        today = fields.Date.context_today(self)
        for partner in self:
            partner.ruteo_is_due = (
                not partner.ruteo_last_visit
                or (partner.ruteo_next_visit_due and partner.ruteo_next_visit_due <= today)
            )

    def _ruteo_register_visit(self, when=None):
        """Registra una visita presencial hoy (o en la fecha dada). La usará el
        cierre de la actividad de visita (Pieza 5)."""
        visit_date = when or fields.Date.context_today(self)
        self.write({'ruteo_last_visit': visit_date})

    # ─────────── Computeds ───────────
    @api.depends('partner_latitude', 'partner_longitude')
    def _compute_ruteo_is_located(self):
        for partner in self:
            lat, lng = partner.partner_latitude, partner.partner_longitude
            partner.ruteo_is_located = bool(
                lat and lng and not (abs(lat) < 1e-4 and abs(lng) < 1e-4)
            )

    # ─────────── Helpers ───────────
    def _ruteo_has_geocodable_address(self):
        """¿Tiene dirección suficiente para intentar geolocalizar?"""
        self.ensure_one()
        return bool(self.street or self.city)

    def _ruteo_flag_pending(self):
        """Marca los partners geocodificables de self como pendientes de ubicar.
        Escribe solo flags (no campos de dirección) → no reentra en write()."""
        to_flag = self.filtered(lambda p: p._ruteo_has_geocodable_address())
        if to_flag:
            super(ResPartner, to_flag.sudo()).write({
                'ruteo_geo_pending': True,
                'ruteo_geo_status': 'pending',
            })

    # ─────────── Enganches create/write ───────────
    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners._ruteo_flag_pending()
        return partners

    def write(self, vals):
        res = super().write(vals)
        if ADDRESS_TRIGGER_FIELDS & set(vals):
            self._ruteo_flag_pending()
        return res

    # ─────────── Geolocalización ───────────
    def action_ruteo_geolocalize(self):
        """Botón de la ficha: ubicar este cliente ahora mismo."""
        self._ruteo_geolocalize_batch()
        return True

    def _ruteo_geolocalize_batch(self, throttle=False):
        """Geolocaliza cada partner de self con el proveedor configurado
        (OpenStreetMap por defecto). Tolerante a fallos y guardado."""
        for partner in self:
            partner = partner.sudo()
            partner.ruteo_geo_last_try = fields.Datetime.now()
            try:
                partner.geo_localize()
                if partner.ruteo_is_located:
                    partner.write({
                        'ruteo_geo_pending': False,
                        'ruteo_geo_status': 'ok',
                        'ruteo_geo_message': False,
                    })
                    _logger.info(
                        "📍 Ruteo: %s ubicado en (%s, %s)",
                        partner.name, partner.partner_latitude, partner.partner_longitude,
                    )
                else:
                    # Sale de la cola automática para no reintentar en loop ni
                    # saturar al proveedor. Al corregir la dirección, write() lo
                    # vuelve a encolar solo; o se reintenta con el botón.
                    partner.write({
                        'ruteo_geo_pending': False,
                        'ruteo_geo_status': 'failed',
                        'ruteo_geo_message': "El geocodificador no devolvió coordenadas para esta dirección.",
                    })
                    _logger.warning(
                        "📍 Ruteo: sin coordenadas para %s (dir: %s, %s)",
                        partner.name, partner.street, partner.city,
                    )
            except Exception as exc:  # noqa: BLE001 — nunca romper save/cron por geo
                partner.write({
                    'ruteo_geo_pending': False,
                    'ruteo_geo_status': 'failed',
                    'ruteo_geo_message': str(exc)[:200],
                })
                _logger.exception("📍 Ruteo: error geolocalizando %s", partner.name)
            if throttle:
                # Política de uso de Nominatim: máximo 1 request por segundo.
                time.sleep(1.1)

    @api.model
    def _cron_ruteo_geocode_pending(self, limit=30):
        """Cron de respaldo: geolocaliza en lote los clientes pendientes.
        Acotado a carteras de vendedores (user_id) para no barrer los miles de
        contactos sueltos ni saturar al proveedor."""
        pending = self.sudo().search([
            ('ruteo_geo_pending', '=', True),
            ('user_id', '!=', False),
        ], limit=limit, order='ruteo_geo_last_try asc, id asc')
        if not pending:
            return
        _logger.info("📍 Ruteo cron: geolocalizando %s cliente(s) pendiente(s)", len(pending))
        pending._ruteo_geolocalize_batch(throttle=True)
