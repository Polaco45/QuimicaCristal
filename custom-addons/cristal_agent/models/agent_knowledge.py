# -*- coding: utf-8 -*-
"""
Base de conocimiento del agente.

El agente consulta esta tabla antes de responder a cualquier mensaje, para
tener contexto actualizado del negocio (políticas, ofertas, FAQs, observaciones).

Hay 3 formas de poblarla:
1. Manual desde la UI de Odoo
2. Joaco le habla a Claudio en el canal interno y Claudio detecta enseñanza
   → llama al tool add_knowledge → crea entry acá
3. Default knowledge cargado al instalar el módulo (data/default_knowledge.xml)

Categorías:
- precio: precios manuales o excepciones
- politica_comercial: plazos, descuentos, formas de pago
- oferta_activa: promociones temporales (con fecha de vencimiento)
- producto: info técnica de productos
- regla_negocio: reglas operativas que define Joaco
- observacion_cliente: lo que el bot sabe sobre un cliente puntual
- faq: respuestas a preguntas frecuentes
- evento: cosas puntuales (feriados, mudanzas, problemas de stock)
- estrategia_marketing: tono, mensajes de campaña
"""
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class CristalAgentKnowledge(models.Model):
    _name = 'cristal.agent.knowledge'
    _description = "Cristal Agent — Base de conocimiento"
    _order = 'priority desc, write_date desc'
    _rec_name = 'name'

    name = fields.Char(
        string="Título",
        required=True,
        help="Título corto descriptivo. Ej: 'Plazos de pago para Plata', 'Oferta limpiavidrios octubre'.",
    )
    display_name = fields.Char(
        string="Nombre completo",
        compute='_compute_display_name',
        store=True,
    )
    category = fields.Selection([
        ('precio', 'Precio'),
        ('politica_comercial', 'Política comercial'),
        ('oferta_activa', 'Oferta activa'),
        ('producto', 'Producto'),
        ('regla_negocio', 'Regla de negocio'),
        ('observacion_cliente', 'Observación de cliente'),
        ('faq', 'FAQ'),
        ('evento', 'Evento puntual'),
        ('estrategia_marketing', 'Estrategia / Marketing'),
        ('otro', 'Otro'),
    ], string="Categoría", required=True, default='regla_negocio', index=True)

    content = fields.Text(
        string="Contenido",
        required=True,
        help="Texto que el bot va a leer. Sé específico y conciso. "
             "Lo que escribas acá impacta directo en cómo responde a clientes.",
    )

    # ─────────── Vigencia ───────────
    active = fields.Boolean(string="Activo", default=True, index=True)
    valid_from = fields.Date(
        string="Vigente desde",
        help="Si se setea, el bot solo lo aplica desde esta fecha.",
    )
    valid_until = fields.Date(
        string="Vigente hasta",
        help="Si se setea, el bot solo lo aplica hasta esta fecha. "
             "Después se desactiva automáticamente vía cron.",
    )

    # ─────────── Targeting ───────────
    applies_to = fields.Selection([
        ('all', 'Todos los clientes Mayoristas'),
        ('level_bronce', 'Solo Bronce'),
        ('level_plata', 'Solo Plata'),
        ('level_oro', 'Solo Oro'),
        ('specific_partners', 'Clientes específicos'),
    ], string="Aplica a", default='all', required=True)

    partner_ids = fields.Many2many(
        'res.partner',
        string="Clientes específicos",
        help="Solo si applies_to = 'specific_partners'.",
    )

    # ─────────── Metadata ───────────
    source = fields.Selection([
        ('manual', 'Carga manual'),
        ('chat_joaco', 'Aprendido en chat con Joaco'),
        ('auto_observation', 'Observación automática del bot'),
        ('default', 'Conocimiento inicial'),
    ], string="Origen", default='manual', required=True)

    priority = fields.Integer(
        string="Prioridad",
        default=10,
        help="Cuanto más alto, primero lo lee el bot. Útil cuando hay info "
             "que se contradice (la prioridad alta gana). Default: 10.",
    )

    tags = fields.Char(
        string="Tags (separados por coma)",
        help="Para búsqueda. Ej: 'descuento, mayorista, formato5l'",
    )

    times_used = fields.Integer(
        string="Veces consultado",
        default=0,
        readonly=True,
        help="Cuántas veces el bot consultó este conocimiento.",
    )

    # ─────────── Métodos ───────────
    @api.model
    def search_for_agent(self, category=None, partner_id=None, level=None, limit=20):
        """
        Busca conocimiento aplicable a la situación actual.

        Args:
            category: filtrar por categoría (None = todas)
            partner_id: filtrar conocimiento aplicable a este partner
            level: nivel del partner ('bronce', 'plata', 'oro') para filtrar
            limit: máximo de resultados

        Returns:
            Lista de dicts con {id, name, category, content, priority}
        """
        today = fields.Date.today()

        # Dominio base: activos y vigentes
        # Estructura: active AND (valid_from null OR <=today) AND (valid_until null OR >=today)
        domain = [
            ('active', '=', True),
            '|', ('valid_from', '=', False), ('valid_from', '<=', today),
            '|', ('valid_until', '=', False), ('valid_until', '>=', today),
        ]
        if category:
            domain.append(('category', '=', category))

        # Construir cláusulas de targeting de forma robusta usando 'in'
        level_map = {
            'bronce': 'level_bronce',
            'plata': 'level_plata',
            'oro': 'level_oro',
        }
        applies_to_values = ['all']
        if level and level in level_map:
            applies_to_values.append(level_map[level])

        if partner_id:
            # OR: (applies_to in [...]) OR (applies_to='specific_partners' AND partner_ids in [partner_id])
            domain.extend([
                '|',
                ('applies_to', 'in', applies_to_values),
                '&', ('applies_to', '=', 'specific_partners'),
                     ('partner_ids', 'in', [partner_id]),
            ])
        else:
            # Solo applies_to in [...]
            domain.append(('applies_to', 'in', applies_to_values))

        records = self.search(domain, limit=limit, order='priority desc, write_date desc')
        # Incrementar contador de uso
        if records:
            records.sudo().write({'times_used': records[0].times_used + 1})

        return [{
            'id': r.id,
            'name': r.name,
            'category': r.category,
            'content': r.content,
            'priority': r.priority,
        } for r in records]

    @api.model
    def cron_deactivate_expired(self):
        """Cron: desactiva entries cuya fecha de vencimiento ya pasó."""
        today = fields.Date.today()
        expired = self.search([
            ('active', '=', True),
            ('valid_until', '!=', False),
            ('valid_until', '<', today),
        ])
        if expired:
            _logger.info("📚 Cron: desactivando %s entries de KB vencidas", len(expired))
            expired.write({'active': False})

    def name_get(self):
        # name_get ya no se usa en Odoo 17+, pero lo dejamos por compatibilidad
        # con código que lo invoque explícitamente. La UI usa display_name.
        return [(rec.id, rec.display_name or rec.name or '') for rec in self]

    @api.depends('name', 'category')
    def _compute_display_name(self):
        for rec in self:
            cat_label = dict(self._fields['category'].selection).get(rec.category, '')
            rec.display_name = f"[{cat_label}] {rec.name}" if rec.name else ''
