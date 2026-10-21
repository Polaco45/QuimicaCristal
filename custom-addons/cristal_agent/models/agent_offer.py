# -*- coding: utf-8 -*-
"""
Ofertas comerciales activas.

Joaco carga ofertas desde la UI de Odoo. El bot las consulta cuando es
relevante (ej: cliente pregunta precios, cliente está en cadencia de
fidelización, etc.) y las menciona naturalmente al cliente.

Por defecto las ofertas son separadas de los descuentos automáticos del
sistema de niveles BRONCE/PLATA/ORO (que están en el motor del bot).

Reglas de no-canibalización (definidas en el system prompt del bot):
- Descuento de nivel + ofertas de esta tabla: NO acumulan (se aplica el mejor)
- Descuento de nivel + escala por volumen + bonif Oro: SÍ acumulan
"""
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class CristalAgentOffer(models.Model):
    _name = 'cristal.agent.offer'
    _description = "Cristal Agent — Oferta activa"
    _order = 'priority desc, valid_until asc'
    _rec_name = 'name'

    name = fields.Char(string="Nombre de la oferta", required=True)
    description = fields.Text(
        string="Descripción",
        required=True,
        help="Descripción que el bot va a usar al mencionarla al cliente. "
             "Ej: 'Esta semana 10% off en limpiavidrios formato 5L'.",
    )

    # ─────────── Productos / categorías afectadas ───────────
    product_ids = fields.Many2many(
        'product.product',
        string="Productos específicos",
        help="Si está vacío, aplica a la frase libre de descripción.",
    )
    category_ids = fields.Many2many(
        'product.category',
        string="Categorías de producto",
    )

    # ─────────── Modalidad de la oferta ───────────
    offer_type = fields.Selection([
        ('percent_discount', '% de descuento'),
        ('amount_discount', 'Descuento $ fijo'),
        ('bundle', 'Combo / bundle'),
        ('bonus', 'Bonificación (lleva X paga Y, regalo, etc.)'),
        ('volume_scale', 'Escala por volumen (más cantidad, más descuento)'),
        ('other', 'Otro'),
    ], string="Tipo de oferta", required=True, default='percent_discount')

    discount_percent = fields.Float(string="Descuento %", default=0.0)
    discount_amount = fields.Float(string="Descuento $", default=0.0)

    # ─────────── Vigencia ───────────
    valid_from = fields.Date(
        string="Vigente desde",
        default=fields.Date.today,
        required=True,
    )
    valid_until = fields.Date(
        string="Vigente hasta",
        required=True,
    )
    active = fields.Boolean(string="Activa", default=True)

    # ─────────── Targeting ───────────
    applies_to_levels = fields.Selection([
        ('all', 'Todos los Mayoristas'),
        ('bronce', 'Solo Bronce'),
        ('plata', 'Solo Plata'),
        ('oro', 'Solo Oro'),
        ('plata_oro', 'Plata y Oro'),
        ('bronce_plata', 'Bronce y Plata'),
    ], string="Aplica a niveles", default='all', required=True)

    is_exclusive = fields.Boolean(
        string="Oferta exclusiva",
        help="Si es True, esta oferta SOLO la pueden usar los clientes del nivel target. "
             "El bot no la menciona a otros niveles.",
    )

    is_proactive = fields.Boolean(
        string="Comunicación proactiva",
        default=False,
        help="Si es True, el bot la incluye en cadencias proactivas (mensajes salientes). "
             "Si es False, solo la menciona si el cliente pregunta.",
    )

    # ─────────── Frecuencia (solo informativa) ───────────
    frequency = fields.Selection([
        ('weekly', 'Semanal'),
        ('monthly', 'Mensual'),
        ('special', 'Especial / única'),
    ], string="Frecuencia", default='special')

    # ─────────── Metadata ───────────
    priority = fields.Integer(
        string="Prioridad",
        default=10,
        help="Cuanto mayor, más visible para el bot.",
    )
    times_communicated = fields.Integer(
        string="Veces comunicada",
        readonly=True,
        default=0,
    )

    notes = fields.Text(string="Notas internas (no se comunican al cliente)")

    # ─────────── Envío de los lunes (v1.40) ───────────
    # Antes el cron mandaba la oferta vigente de mayor prioridad (aunque fuera de una
    # zona) y le ponía al cliente los primeros 300 caracteres de la descripción, que
    # es la instrucción interna para Claudio. Ahora solo sale la que se marca acá.
    weekly_broadcast = fields.Boolean(
        string="Va en el envío de los lunes",
        help="Si está vigente, es la oferta que el envío automático de los lunes (14 h) "
             "les manda a todos los mayoristas por la plantilla oferta_semanal_general.")
    broadcast_text = fields.Char(
        string="Texto para el cliente (envío de los lunes)",
        help="Lo que lee el cliente después de 'Oferta de la semana:'. Corto (hasta 300 "
             "caracteres), sin saltos de línea.")
    excluded_circuit_ids = fields.Many2many(
        'cristal.agent.circuit', 'cristal_agent_offer_excluded_circuit_rel',
        'offer_id', 'circuit_id', string="No mandar a los circuitos",
        help="Los clientes de estos circuitos de la ruta no reciben el envío de los lunes.")

    @api.constrains('weekly_broadcast', 'broadcast_text')
    def _check_broadcast_text(self):
        from odoo.exceptions import ValidationError
        for rec in self.filtered('weekly_broadcast'):
            text = (rec.broadcast_text or '').strip()
            if not text:
                raise ValidationError(
                    "Para mandarla en el envío de los lunes falta el texto para el cliente.")
            if len(text) > 300:
                raise ValidationError(
                    "El texto para el cliente tiene %s caracteres (máximo 300)." % len(text))

    @api.model
    def get_weekly_broadcast_offer(self, today=None):
        """La oferta vigente marcada para el envío de los lunes (o vacío)."""
        today = today or fields.Date.context_today(self)
        return self.sudo().search([
            ('active', '=', True), ('weekly_broadcast', '=', True),
            ('valid_from', '<=', today), ('valid_until', '>=', today),
        ], limit=1, order='priority desc, write_date desc')

    # ─────────── Métodos ───────────
    @api.model
    def search_for_agent(self, level=None, only_proactive=False, limit=10):
        """
        Devuelve ofertas activas y vigentes aplicables al nivel del cliente.

        Args:
            level: 'bronce', 'plata', 'oro' o None
            only_proactive: si True, solo las marcadas como is_proactive
            limit: máx resultados
        """
        today = fields.Date.today()
        domain = [
            ('active', '=', True),
            ('valid_from', '<=', today),
            ('valid_until', '>=', today),
        ]
        if only_proactive:
            domain.append(('is_proactive', '=', True))

        # Targeting por nivel
        if level:
            level_map = {
                'bronce': ['all', 'bronce', 'bronce_plata'],
                'plata': ['all', 'plata', 'plata_oro', 'bronce_plata'],
                'oro': ['all', 'oro', 'plata_oro'],
            }
            valid_targets = level_map.get(level, ['all'])
            domain.append(('applies_to_levels', 'in', valid_targets))

        records = self.search(domain, limit=limit, order='priority desc, valid_until asc')
        return [{
            'id': r.id,
            'name': r.name,
            'description': r.description,
            'type': r.offer_type,
            'discount_percent': r.discount_percent,
            'discount_amount': r.discount_amount,
            'valid_until': str(r.valid_until) if r.valid_until else '',
            'is_exclusive': r.is_exclusive,
            'applies_to_levels': r.applies_to_levels,
        } for r in records]

    @api.model
    def cron_deactivate_expired(self):
        """Cron: desactiva ofertas vencidas."""
        today = fields.Date.today()
        expired = self.search([
            ('active', '=', True),
            ('valid_until', '<', today),
        ])
        if expired:
            _logger.info("🎁 Cron: desactivando %s ofertas vencidas", len(expired))
            expired.write({'active': False})

    def increment_communicated(self):
        for rec in self:
            rec.times_communicated = (rec.times_communicated or 0) + 1
