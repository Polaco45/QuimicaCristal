# -*- coding: utf-8 -*-
"""
Ruta del camión mayorista — circuitos y localidades.

Un camión sale UNA vez por semana (miércoles desde v1.35; antes jueves) a uno de 4 circuitos, rotando cada 4
semanas: Sur-Oeste → Norte → Este → Sur-Este. Cada circuito agrupa localidades
(con alias para normalizar el texto que escribe el cliente) y tiene su etiqueta de
contacto (res.partner.category 35/32/50/51) ya cargada.

Las SALIDAS concretas (cada miércoles) son registros de `cristal.agent.route.departure`
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


# v1.36 — Alias extra por código (valen en cualquier base, sin depender de los
# registros noupdate). Caso real: un cliente escribió "Olver" (= Holmberg) y Claudio
# lo marcó fuera de zona.
EXTRA_ALIASES = {
    'Holmberg': ['olver', 'olber', 'holver', 'holber', 'olmberg', 'holberg',
                 'holmber', 'holmbergh', 'holmbreg', 'olmber'],
    'Santa Catalina': ['sta catalina', 'catalina', 'santa catalina holmberg'],
    'Las Vertientes': ['vertientes', 'la vertiente', 'las vertiente'],
    'Sampacho': ['sanpacho', 'sampacho cba', 'zampacho'],
    'Suco': ['zuco'],
    'Coronel Moldes': ['cnel moldes', 'crnel moldes', 'moldes', 'coronel molde'],
    'Vicuña Mackenna': ['vicuna', 'vicuna mackenna', 'vicuna mackena', 'vicunia',
                        'vicunia mackenna', 'mackena', 'makena', 'v mackenna'],
    'Tosquita': ['tosquitas'],
    'Coronel Baigorria': ['cnel baigorria', 'baigorria', 'baigoria'],
    'Alcira Gigena': ['alcira gigena', 'gigena', 'alcira', 'jigena'],
    'Berrotarán': ['berrotaran', 'berotaran'],
    'General Cabrera': ['gral cabrera', 'cabrera', 'grl cabrera'],
    'General Deheza': ['gral deheza', 'deheza', 'deeza', 'grl deheza'],
    'Dalmacio Vélez': ['dalmacio velez', 'dalmacio', 'd velez'],
    'Carnerillo': ['carnerilo'],
    'Las Acequias': ['acequias', 'las asequias'],
    'Reducción': ['reduccion', 'la reduccion', 'reducion'],
    'Alejandro Roca': ['alejandro', 'a roca', 'alejandro rocca'],
    'La Carlota': ['carlota', 'la carlota cba'],
    'Chazón': ['chazon'],
    'Bengolea': ['bengolia'],
    'San Basilio': ['basilio'],
    'Adelia María': ['adelia maria', 'adelia', 'a maria'],
    'Monte de los Gauchos': ['monte de los gauchos', 'monte los gauchos'],
}
RIO_CUARTO_ALIASES = {
    'rio 4': 'Río Cuarto', 'rio iv': 'Río Cuarto', 'riocuarto': 'Río Cuarto',
    'rio cuatro': 'Río Cuarto', 'r cuarto': 'Río Cuarto', 'rio iv cordoba': 'Río Cuarto',
    'rio cuarto cordoba': 'Río Cuarto', 'higueras': 'Las Higueras',
}
# Palabras que no distinguen una localidad (no se usan solas para el difuso).
_FUZZY_STOPWORDS = {'general', 'coronel', 'santa', 'santo', 'san', 'las', 'los', 'la',
                    'el', 'de', 'del', 'monte', 'maria', 'rio'}


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


def phonetic_town(text):
    """Clave fonética aproximada (español rioplatense) sobre el texto normalizado:
    h muda, v=b, z/ce/ci=s, ll=y, qu/k=c, letras dobles colapsadas.
    'Olver' → 'olber'; 'Holmberg' → 'olmberg'."""
    t = normalize_town(text)
    if not t:
        return ''
    t = t.replace('ll', 'y').replace('qu', 'k').replace('ce', 'se').replace('ci', 'si')
    t = t.replace('h', '').replace('v', 'b').replace('z', 's').replace('k', 'c')
    out = []
    for ch in t:
        if out and out[-1] == ch:
            continue
        out.append(ch)
    return ''.join(out)


def levenshtein(a, b):
    """Distancia de edición clásica (inserción, borrado, sustitución)."""
    if a == b:
        return 0
    if not a or not b:
        return len(a or b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _fuzzy_limit(key):
    """Distancia máxima aceptada según el largo (más corto = más estricto)."""
    n = len(key.replace(' ', ''))
    if n <= 4:
        return 0
    if n <= 6:
        return 1
    if n <= 10:
        return 2
    return 3


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
        string="Día de salida", default='2',
        help="Día de la semana en que sale el camión (miércoles).")
    partner_category_id = fields.Many2one(
        'res.partner.category', string="Etiqueta de contacto",
        help="Etiqueta (res.partner.category) de los contactos de este circuito.")
    first_departure_date = fields.Date(
        string="Primera salida", required=True,
        help="Fecha de la primera salida de este circuito. La rotación es cada 28 días.")
    town_ids = fields.One2many(
        'cristal.agent.circuit.town', 'circuit_id', string="Localidades")
    departure_ids = fields.One2many(
        'cristal.agent.route.departure', 'circuit_id', string="Salidas")

    # ───────────────────────── Clasificación de ciudad ─────────────────────────
    @api.model
    def classify_city(self, text):
        """Clasifica un texto de ciudad. Devuelve un dict:
        {'kind': 'rio_cuarto'|'circuit'|'maybe'|'fuera_zona'|'empty',
         'circuit': record|False, 'canonical': str, 'candidate': str (solo 'maybe')}.

        v1.36: si no hay coincidencia exacta (nombre o alias) pero el texto se parece
        mucho a una localidad conocida (similitud fonética + Levenshtein), devuelve
        'maybe' con el candidato: el bot PREGUNTA ("¿Se refiere a Holmberg?") en vez
        de marcarlo fuera de zona."""
        norm = normalize_town(text)
        if not norm:
            return {'kind': 'empty', 'circuit': False, 'canonical': ''}
        rc_keys = dict(RIO_CUARTO_TOWNS)
        rc_keys.update(RIO_CUARTO_ALIASES)
        if norm in rc_keys:
            return {'kind': 'rio_cuarto', 'circuit': False, 'canonical': rc_keys[norm]}
        Town = self.env['cristal.agent.circuit.town'].sudo()
        towns = Town.search([('circuit_id.active', '=', True)])
        for town in towns:
            if norm in town._normalized_keys():
                return {'kind': 'circuit', 'circuit': town.circuit_id,
                        'canonical': town.name}
        # ── Difuso: ¿se parece a alguna? ──
        target = phonetic_town(norm)
        single = len(norm.split()) == 1
        scored = []  # (distancia, canonical, circuit|False)

        def consider(key, canonical, circuit):
            pk = phonetic_town(key)
            options = [(levenshtein(target, pk), _fuzzy_limit(key))]
            if single:
                for w in key.split():
                    if len(w) >= 5 and w not in _FUZZY_STOPWORDS:
                        options.append((levenshtein(target, phonetic_town(w)),
                                        _fuzzy_limit(w)))
            for dist, limit in options:
                if dist <= limit:
                    scored.append((dist, canonical, circuit))

        for key, canonical in rc_keys.items():
            consider(key, canonical, False)
        for town in towns:
            for key in town._normalized_keys():
                consider(key, town.name, town.circuit_id)
        if scored:
            best = min(s[0] for s in scored)
            winners = {(s[1], s[2].id if s[2] else 0) for s in scored if s[0] == best}
            if len(winners) == 1:
                _d, canonical, circuit = next(s for s in scored if s[0] == best)
                return {'kind': 'maybe', 'circuit': circuit or False,
                        'canonical': (text or '').strip(), 'candidate': canonical}
        return {'kind': 'fuera_zona', 'circuit': False,
                'canonical': (text or '').strip()}

    @api.model
    def resolve_circuit(self, text):
        """Devuelve el circuito para un texto de ciudad, o False."""
        info = self.classify_city(text)
        return info['circuit'] if info.get('kind') == 'circuit' else False

    # ───────────────────────── Próxima salida ─────────────────────────
    # Estados de una salida que todavía toma pedidos. 'rescate' es el Plan B de la
    # MISMA salida (envío gratis desde $75.000 + cortesía): sigue abierta.
    OPEN_STATES = ('preventa', 'rescate')

    def get_next_departure(self, reference_dt=None):
        """Devuelve la próxima salida (`cristal.agent.route.departure`) que toma
        pedidos (preventa o rescate) cuyo cierre de preventa todavía NO pasó.
        reference_dt: datetime naive UTC (default: ahora). Si no hay ninguna,
        devuelve un recordset vacío (el bot NO inventa fecha: escala)."""
        self.ensure_one()
        now = reference_dt or fields.Datetime.now()
        deps = self.departure_ids.filtered(
            lambda d: d.state in self.OPEN_STATES).sorted('date')
        for dep in deps:
            if now < dep.get_preventa_cutoff():
                return dep
        return self.env['cristal.agent.route.departure']

    # ───────────────────────── Botones ─────────────────────────
    def _notify(self, title, message):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': title, 'message': message, 'type': 'success'}}

    def action_generate_departures(self):
        created = self.env['cristal.agent.route.departure'].sudo().generate_upcoming(weeks=12)
        return self._notify("Salidas", f"Se generaron {created} salidas nuevas (12 semanas).")

    def action_backfill_button(self):
        c = self.action_backfill_truck_circuits()
        return self._notify(
            "Circuitos de contactos",
            f"Por etiqueta: {c['by_tag']} · por ciudad: {c['by_city']} · "
            f"ya estaban: {c['skipped_has_circuit']} · fuera de circuito: {c['fuera']}")

    # ───────────────────────── Backfill de partners ─────────────────────────
    @api.model
    def action_backfill_truck_circuits(self, partner_ids=None):
        """Recalcula truck_circuit_id en los partners (todos, o `partner_ids`).
        Fuente de verdad: las ETIQUETAS de circuito ya cargadas (35/32/50/51).
        Si el partner tiene una etiqueta de circuito, se respeta y NUNCA se pisa.
        La ciudad se usa SOLO si el partner no tiene ninguna etiqueta de circuito.
        Devuelve un dict con el conteo por origen (para el log de migración)."""
        Partner = self.env['res.partner'].sudo()
        scope = [('id', 'in', list(partner_ids))] if partner_ids else []
        circuits = self.search([])
        by_category = {c.partner_category_id.id: c
                       for c in circuits if c.partner_category_id}
        counts = {'by_tag': 0, 'by_city': 0, 'skipped_has_circuit': 0, 'fuera': 0}

        # 1) Por etiqueta (fuente de verdad, no se pisa)
        for cat_id, circuit in by_category.items():
            partners = Partner.search(scope + [('category_id', 'in', [cat_id])])
            for p in partners:
                if p.truck_circuit_id and p.truck_circuit_id.id == circuit.id:
                    counts['skipped_has_circuit'] += 1
                    continue
                p.with_context(skip_circuit_tag_sync=True).truck_circuit_id = circuit.id
                counts['by_tag'] += 1

        # 2) Por ciudad, SOLO los que no tienen etiqueta de circuito ni truck_circuit_id
        cat_ids = list(by_category.keys())
        no_tag = Partner.search(scope + [
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
        for a in EXTRA_ALIASES.get(self.name, []):
            keys.add(normalize_town(a))
        for a in (self.aliases or '').split(','):
            a = normalize_town(a)
            if a:
                keys.add(a)
        return keys
