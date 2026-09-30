# -*- coding: utf-8 -*-
"""
Ruta del camión mayorista — circuitos y localidades.

Un camión sale UNA vez por semana (jueves) a uno de 4 circuitos, rotando cada 4
semanas: Sur-Oeste → Norte → Este → Sur-Este. Cada circuito agrupa localidades
(con alias para normalizar el texto que escribe el cliente) y tiene su etiqueta de
contacto (res.partner.category 35/32/50/51) ya cargada.

Las SALIDAS concretas (cada jueves) son registros de `cristal.agent.route.departure`
(ver agent_route_departure.py); acá vive la definición del circuito + la rotación.
"""
import logging
import unicodedata

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Localidades que se atienden como Río Cuarto (reparto normal, NO ruta de camión).
RIO_CUARTO_TOWNS = {
    'rio cuarto': 'Río Cuarto',
    'las higueras': 'Las Higueras',
    'banda norte': 'Banda Norte',
    'alberdi': 'Alberdi',
}


# Abreviaturas frecuentes en localidades (se expanden al normalizar).
_ABBREVIATIONS = {
    'gral': 'general',
    'cnel': 'coronel',
    'sta': 'santa',
    'sto': 'santo',
}


def normalize_town(text):
    """Normaliza una localidad: sin acentos (incl. acento grave), minúsculas,
    sin puntuación, espacios colapsados y abreviaturas expandidas.
    'Chajàn' → 'chajan'; 'GRAL CABRERA' → 'general cabrera'."""
    if not text:
        return ''
    txt = unicodedata.normalize('NFKD', str(text))
    txt = ''.join(c for c in txt if not unicodedata.combining(c))
    txt = txt.lower()
    for ch in '.,;:()-_/':
        txt = txt.replace(ch, ' ')
    words = [_ABBREVIATIONS.get(w, w) for w in txt.split()]
    return ' '.join(words)


class CristalAgentCircuit(models.Model):
    _name = 'cristal.agent.circuit'
    _description = 'Circuito de ruta del camión mayorista'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(
        string="Orden de rotación", default=10,
        help="Orden en que rota el camión entre circuitos.")
    weekday = fields.Selection(
        [('0', 'Lunes'), ('1', 'Martes'), ('2', 'Miércoles'), ('3', 'Jueves'),
         ('4', 'Viernes'), ('5', 'Sábado'), ('6', 'Domingo')],
        string="Día de salida", default='3',
        help="Día de la semana en que sale el camión (jueves).")
    partner_category_id = fields.Many2one(
        'res.partner.category', string="Etiqueta de contacto",
        help="Etiqueta (res.partner.category) de los contactos de este circuito.")
    first_departure_date = fields.Date(
        string="Primera salida", required=True,
        help="Fecha del primer jueves de este circuito. La rotación es cada 28 días.")
    town_ids = fields.One2many(
        'cristal.agent.circuit.town', 'circuit_id', string="Localidades")
    departure_ids = fields.One2many(
        'cristal.agent.route.departure', 'circuit_id', string="Salidas")

    # ───────────────────────── Clasificación de ciudad ─────────────────────────
    @api.model
    def classify_city(self, text):
        """Clasifica un texto de ciudad. Devuelve un dict:
        {'kind': 'rio_cuarto'|'circuit'|'fuera_zona'|'empty',
         'circuit': record|False, 'canonical': str}."""
        norm = normalize_town(text)
        if not norm:
            return {'kind': 'empty', 'circuit': False, 'canonical': ''}
        if norm in RIO_CUARTO_TOWNS:
            return {'kind': 'rio_cuarto', 'circuit': False,
                    'canonical': RIO_CUARTO_TOWNS[norm]}
        Town = self.env['cristal.agent.circuit.town'].sudo()
        for town in Town.search([('circuit_id.active', '=', True)]):
            if norm in town._normalized_keys():
                return {'kind': 'circuit', 'circuit': town.circuit_id,
                        'canonical': town.name}
        return {'kind': 'fuera_zona', 'circuit': False,
                'canonical': (text or '').strip()}

    @api.model
    def resolve_circuit(self, text):
        """Devuelve el circuito para un texto de ciudad, o False."""
        return self.classify_city(text).get('circuit') or False

    # ───────────────────────── Próxima salida ─────────────────────────
    def get_next_departure(self, reference_dt=None):
        """Devuelve el registro de salida (`cristal.agent.route.departure`) en
        estado 'preventa' cuyo cierre de preventa todavía NO pasó, el más próximo.
        Si no hay ninguna en preventa vigente, devuelve la próxima salida futura
        que no esté realizada (fallback)."""
        self.ensure_one()
        now = reference_dt or fields.Datetime.now()
        deps = self.departure_ids.filtered(
            lambda d: d.state == 'preventa').sorted('date')
        for dep in deps:
            if now <= dep.get_preventa_cutoff():
                return dep
        # Fallback: próxima salida no realizada por fecha.
        future = self.departure_ids.filtered(
            lambda d: d.state != 'realizada').sorted('date')
        today = fields.Date.context_today(self)
        for dep in future:
            if dep.date >= today:
                return dep
        return self.env['cristal.agent.route.departure']

    # ───────────────────────── Backfill de partners ─────────────────────────
    @api.model
    def action_backfill_truck_circuits(self):
        """Recalcula truck_circuit_id en todos los partners.
        Fuente de verdad: las ETIQUETAS de circuito ya cargadas (35/32/50/51).
        Si el partner tiene una etiqueta de circuito, se respeta y NUNCA se pisa.
        La ciudad se usa SOLO si el partner no tiene ninguna etiqueta de circuito.
        Devuelve un dict con el conteo por origen (para el log de migración)."""
        Partner = self.env['res.partner'].sudo()
        circuits = self.search([])
        by_category = {c.partner_category_id.id: c
                       for c in circuits if c.partner_category_id}
        counts = {'by_tag': 0, 'by_city': 0, 'skipped_has_circuit': 0, 'fuera': 0}

        # 1) Por etiqueta (fuente de verdad, no se pisa)
        for cat_id, circuit in by_category.items():
            partners = Partner.search([('category_id', 'in', [cat_id])])
            for p in partners:
                if p.truck_circuit_id and p.truck_circuit_id.id == circuit.id:
                    counts['skipped_has_circuit'] += 1
                    continue
                p.with_context(skip_circuit_tag_sync=True).truck_circuit_id = circuit.id
                counts['by_tag'] += 1

        # 2) Por ciudad, SOLO los que no tienen etiqueta de circuito ni truck_circuit_id
        cat_ids = list(by_category.keys())
        no_tag = Partner.search([
            ('category_id', 'not in', cat_ids),
            ('truck_circuit_id', '=', False),
            ('city', '!=', False),
        ])
        for p in no_tag:
            info = self.classify_city(p.city)
            if info['kind'] == 'circuit' and info['circuit']:
                p.truck_circuit_id = info['circuit'].id  # sincroniza etiqueta vía write
                counts['by_city'] += 1
            elif info['kind'] == 'fuera_zona':
                counts['fuera'] += 1
        _logger.info("Backfill truck_circuit_id: %s", counts)
        return counts


class CristalAgentCircuitTown(models.Model):
    _name = 'cristal.agent.circuit.town'
    _description = 'Localidad de un circuito de ruta'
    _order = 'circuit_id, name'

    name = fields.Char(required=True, string="Localidad (grafía canónica)")
    circuit_id = fields.Many2one(
        'cristal.agent.circuit', required=True, ondelete='cascade', index=True)
    aliases = fields.Char(
        string="Alias",
        help="Variantes de escritura separadas por coma (ej: 'Mackenna, Maqueda').")
    optional = fields.Boolean(
        string="Desvío opcional",
        help="Localidad de desvío opcional (ej: Chaján, Achiras).")

    def _normalized_keys(self):
        """Set de claves normalizadas (nombre + alias) para matchear texto libre."""
        self.ensure_one()
        keys = {normalize_town(self.name)}
        for a in (self.aliases or '').split(','):
            a = normalize_town(a)
            if a:
                keys.add(a)
        return keys
