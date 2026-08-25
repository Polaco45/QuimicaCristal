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
import re
import time
from datetime import timedelta
from urllib.parse import quote

import requests

from odoo import api, fields, models

# Geocodificador oficial argentino (datos.gob.ar) — gratis, sin API key y mucho
# más preciso que OpenStreetMap para direcciones locales.
GEOREF_URL = 'https://apis.datos.gob.ar/georef/api/direcciones'

_logger = logging.getLogger(__name__)

# Campos de dirección que, al cambiar, disparan una nueva geolocalización.
ADDRESS_TRIGGER_FIELDS = {'street', 'street2', 'city', 'zip', 'state_id', 'country_id'}

# Frecuencia de visita (días) según el nivel mayorista que calcula cristal_agent.
RUTEO_FREQ_BY_LEVEL = {'oro': 7, 'plata': 15, 'bronce': 30}
# Cadencia de captación para clientes nuevos/prospectos todavía sin nivel.
RUTEO_FREQ_PROSPECT = 15

# Tipos de visita (compartido con la visita de ruta para el badge).
RUTEO_VISIT_TYPES = [
    ('primera_visita', 'Primera visita'),
    ('relevamiento', 'Relevamiento'),
    ('cierre', 'Cierre de venta'),
    ('reposicion', 'Reposición'),
    ('reactivacion', 'Reactivación'),
]

# Caja geográfica de la zona de trabajo (Río Cuarto y alrededores). Si el
# geocodificador devuelve un punto fuera de esta caja, seguro erró (ej. el
# centroide genérico de la provincia) → se marca para revisar en vez de darlo
# por bueno.
RUTEO_GEO_BBOX = {'lat_min': -34.6, 'lat_max': -32.0, 'lng_min': -65.6, 'lng_max': -63.4}


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ─────────── Estado del geocodificado para el ruteo ───────────
    ruteo_geo_status = fields.Selection([
        ('pending', 'Pendiente de ubicar'),
        ('ok', 'Ubicado'),
        ('review', 'Revisar (fuera de zona)'),
        ('failed', 'No se pudo ubicar'),
        ('no_address', 'Sin dirección'),
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

    # ─────────── Prioridad y tipo de visita (Pieza 4) ───────────
    ruteo_visit_type = fields.Selection(
        RUTEO_VISIT_TYPES, string="Tipo de visita", compute='_compute_ruteo_priority',
        help="Qué clase de visita es, según la etapa del CRM y el estado del cliente.")
    ruteo_priority_score = fields.Integer(
        string="Prioridad de visita", compute='_compute_ruteo_priority',
        help="Cuánto más alto, más urgente visitarlo. Define el orden de la ruta.")
    ruteo_pin_color = fields.Integer(
        string="Color de pin", compute='_compute_ruteo_priority',
        help="Índice de color Odoo asociado al tipo de visita (para kanban/mapa).")

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
        """Registra una visita presencial hoy (o en la fecha dada). La usa el
        cierre de la actividad de visita (Pieza 5)."""
        visit_date = when or fields.Date.context_today(self)
        self.write({'ruteo_last_visit': visit_date})

    # ─────────── Prioridad / tipo de visita (Pieza 4) ───────────
    # Colores Odoo: 1 rojo, 2 naranja, 4 celeste, 5 violeta, 10 verde.
    _RUTEO_TYPE_BASE = {
        'cierre': 100, 'reactivacion': 80, 'relevamiento': 70,
        'primera_visita': 60, 'reposicion': 50,
    }
    _RUTEO_TYPE_COLOR = {
        'cierre': 1, 'reactivacion': 2, 'relevamiento': 5,
        'primera_visita': 10, 'reposicion': 4,
    }

    def _ruteo_best_open_lead(self):
        """La oportunidad abierta más avanzada del cliente (la más cerca de cerrar).

        Con sudo por lo mismo que _visit_family_best_lead: alimenta computes de
        la ficha del contacto, que también abre gente sin acceso al CRM.
        """
        self.ensure_one()
        leads = self.env['crm.lead'].sudo().search([
            ('partner_id', '=', self.id),
            ('type', '=', 'opportunity'),
        ])
        if not leads:
            return self.env['crm.lead']
        return max(leads, key=lambda lead: lead.stage_id.sequence or 0)

    def _ruteo_stage_visit_type(self, stage):
        """Traduce la etapa del CRM a un tipo de visita."""
        if not stage:
            return 'primera_visita'
        seq = stage.sequence or 0
        name = (stage.name or '').lower()
        if 'tibio' in name:
            return 'reactivacion'
        if 5 <= seq <= 8:            # Propuesta / Negociación / Última oferta / Consulta final
            return 'cierre'
        if seq in (2, 3, 4):         # Calificado / Relevamiento agendado / Relevado
            return 'relevamiento'
        if seq == 9 or 'ganado' in name:
            return 'reposicion'
        return 'primera_visita'      # Nuevo / Contactado / otros

    def _ruteo_is_customer(self):
        self.ensure_one()
        return bool(self.agent_last_purchase_at) or self.agent_strategy_phase in (
            'phase_3_first_purchase_done', 'phase_3_onboarding',
            'phase_4_active_customer', 'phase_5_loyalty', 'reactivated')

    @api.depends('agent_level', 'agent_churn_score', 'agent_strategy_phase',
                 'agent_last_purchase_at', 'ruteo_is_due', 'ruteo_next_visit_due')
    def _compute_ruteo_priority(self):
        for partner in self:
            stage = partner._ruteo_best_open_lead().stage_id
            vtype = partner._ruteo_stage_visit_type(stage)
            churn = partner.agent_churn_score or 0.0
            # Un cliente que ya compra y no está en pipeline avanzado: reposición
            # o reactivación según riesgo.
            if vtype == 'primera_visita' and partner._ruteo_is_customer():
                vtype = ('reactivacion'
                         if churn >= 50 or partner.agent_strategy_phase in ('churning', 'lost')
                         else 'reposicion')
            score = self._RUTEO_TYPE_BASE.get(vtype, 50)
            if partner.ruteo_is_due:
                score += 20
            score += int(churn * 0.2)
            score += {'oro': 15, 'plata': 10, 'bronce': 5}.get(partner.agent_level, 0)
            partner.ruteo_visit_type = vtype
            partner.ruteo_priority_score = min(score, 200)
            partner.ruteo_pin_color = self._RUTEO_TYPE_COLOR.get(vtype, 0)

    def _ruteo_visit_reason(self):
        """Texto corto de por qué visitarlo, para la actividad."""
        self.ensure_one()
        parts = []
        days = self.agent_days_since_last_purchase or 0
        if not self.ruteo_last_visit and not self._ruteo_is_customer():
            parts.append("primera visita")
        elif days > 0:
            parts.append("%s días sin comprar" % days)
        if self.agent_level and self.agent_level != 'none':
            parts.append("cliente %s" % self.agent_level)
        if self.agent_churn_score and self.agent_churn_score >= 50:
            parts.append("riesgo de fuga")
        return " · ".join(parts) or "visita de ruta"

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

    def _ruteo_coords_in_zone(self):
        """¿Las coordenadas caen dentro de la zona de trabajo (Río Cuarto)?"""
        self.ensure_one()
        b = RUTEO_GEO_BBOX
        return (b['lat_min'] <= self.partner_latitude <= b['lat_max']
                and b['lng_min'] <= self.partner_longitude <= b['lng_max'])

    def _ruteo_flag_pending(self):
        """Marca los partners geocodificables como pendientes de ubicar, y los
        que no tienen dirección como 'Sin dirección' (para que no se pierdan en
        silencio). Escribe solo flags → no reentra en write()."""
        to_flag = self.filtered(lambda p: p._ruteo_has_geocodable_address())
        if to_flag:
            super(ResPartner, to_flag.sudo()).write({
                'ruteo_geo_pending': True,
                'ruteo_geo_status': 'pending',
            })
        no_addr = (self - to_flag).filtered(lambda p: not p.ruteo_is_located)
        if no_addr:
            super(ResPartner, no_addr.sudo()).write({
                'ruteo_geo_pending': False,
                'ruteo_geo_status': 'no_address',
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

    def action_ruteo_geolocalize_selected(self):
        """Acción masiva: geolocaliza los seleccionados que tengan dirección y
        marca 'Sin dirección' a los que no. Pensado para el menú Acción de la
        lista de contactos / oportunidades (seleccionar varios y ubicarlos)."""
        con_direccion = self.filtered(lambda p: p._ruteo_has_geocodable_address())
        sin_direccion = (self - con_direccion).filtered(lambda p: not p.ruteo_is_located)
        if sin_direccion:
            sin_direccion.sudo().write({
                'ruteo_geo_pending': False, 'ruteo_geo_status': 'no_address'})
        if con_direccion:
            con_direccion._ruteo_geolocalize_batch(throttle=True)
        _logger.info("📍 Ruteo: geolocalización masiva — %s con dirección, %s sin dirección",
                     len(con_direccion), len(sin_direccion))
        return True

    def action_ruteo_open_maps(self):
        """Abre Google Maps con la dirección/coordenadas del cliente (navegación)."""
        self.ensure_one()
        if self.ruteo_is_located:
            destination = "%s,%s" % (self.partner_latitude, self.partner_longitude)
        else:
            destination = ", ".join(
                p for p in [self.street, self.city, (self.country_id.name or '')] if p)
        return {
            'type': 'ir.actions.act_url',
            'url': "https://www.google.com/maps/dir/?api=1&destination=%s" % quote(destination or ''),
            'target': 'new',
        }

    def _ruteo_localidad_provincia(self):
        """Localidad y provincia a usar en el geocodificado. Si el cliente no
        tiene ciudad cargada, se asume la zona de reparto (Río Cuarto por defecto,
        Las Higueras si corresponde), para no geocodificar 'a ciegas'."""
        self.ensure_one()
        localidad = (self.city or '').strip()
        if not localidad:
            localidad = 'Las Higueras' if self.agent_zone == 'las_higueras' else 'Río Cuarto'
        provincia = (self.state_id.name or 'Córdoba').strip()
        return localidad, provincia

    @staticmethod
    def _georef_lookup(direccion, localidad, provincia):
        """Consulta georef (datos.gob.ar). Devuelve (lat, lon, nomenclatura) o None."""
        if not direccion:
            return None
        params = {'direccion': direccion, 'localidad': localidad,
                  'provincia': provincia, 'max': 1}
        resp = requests.get(GEOREF_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json().get('direcciones') or []
        if not data:
            return None
        ubic = (data[0].get('ubicacion') or {})
        lat, lon = ubic.get('lat'), ubic.get('lon')
        if lat in (None, 0) or lon in (None, 0):
            return None
        return (lat, lon, data[0].get('nomenclatura'))

    def _ruteo_geocode(self):
        """Geocodifica el cliente con georef (preciso para direcciones argentinas).
        Devuelve (lat, lon, etiqueta, exacto) o None. 'exacto' = matcheó con altura."""
        self.ensure_one()
        street = (self.street or '').strip()
        if not street:
            return None
        localidad, provincia = self._ruteo_localidad_provincia()
        result = self._georef_lookup(street, localidad, provincia)
        if result:
            return result + (True,)
        # Reintento sin la altura (a veces frena el match): al menos ubica la calle.
        street_no_num = re.sub(r'\d+', '', street).strip(' ,.-')
        if street_no_num and street_no_num.lower() != street.lower():
            result = self._georef_lookup(street_no_num, localidad, provincia)
            if result:
                return result + (False,)
        return None

    def _ruteo_geolocalize_batch(self, throttle=False):
        """Geolocaliza cada partner de self con georef (geocodificador oficial
        argentino, gratis y preciso). Tolerante a fallos y guardado."""
        for partner in self:
            partner = partner.sudo()
            partner.ruteo_geo_last_try = fields.Datetime.now()
            try:
                geo = partner._ruteo_geocode()
                if geo:
                    lat, lon, label, exacto = geo
                    partner.write({
                        'partner_latitude': lat,
                        'partner_longitude': lon,
                        'date_localization': fields.Date.context_today(partner),
                    })
                    if not partner._ruteo_coords_in_zone():
                        partner.write({
                            'ruteo_geo_pending': False,
                            'ruteo_geo_status': 'review',
                            'ruteo_geo_message': "Fuera de zona de Río Cuarto — revisá: %s" % (label or ''),
                        })
                    elif exacto:
                        partner.write({
                            'ruteo_geo_pending': False,
                            'ruteo_geo_status': 'ok',
                            'ruteo_geo_message': label or False,
                        })
                        _logger.info("📍 Ruteo: %s → %s (%s, %s)", partner.name, label, lat, lon)
                    else:
                        # Ubicó la calle pero no la altura exacta.
                        partner.write({
                            'ruteo_geo_pending': False,
                            'ruteo_geo_status': 'review',
                            'ruteo_geo_message': "Altura aproximada (revisá): %s" % (label or ''),
                        })
                else:
                    partner.write({
                        'ruteo_geo_pending': False,
                        'ruteo_geo_status': 'failed',
                        'ruteo_geo_message': "No se encontró la dirección. Revisá calle, altura y ciudad.",
                    })
                    _logger.warning("📍 Ruteo: sin resultado para %s (dir: %s, %s)",
                                    partner.name, partner.street, partner.city)
            except Exception as exc:  # noqa: BLE001 — nunca romper save/cron por geo
                partner.write({
                    'ruteo_geo_pending': False,
                    'ruteo_geo_status': 'failed',
                    'ruteo_geo_message': str(exc)[:200],
                })
                _logger.exception("📍 Ruteo: error geolocalizando %s", partner.name)
            if throttle:
                time.sleep(0.6)

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
