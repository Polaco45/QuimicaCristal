# -*- coding: utf-8 -*-
"""
Extensión de res.partner para cobranza.

El corazón de la "coherencia" que pidió Joaco vive acá: `cobranza_snapshot()`
separa SIEMPRE las facturas en VENCIDAS vs POR VENCER (en los próximos N días),
calcula el total vencido y los días de mora de la factura más vieja. Tanto el
reporte de estado de cuenta como el motor de cadencia usan este mismo método,
así el PDF y el mensaje nunca se contradicen.
"""
import logging
from datetime import timedelta

from odoo import models, fields, api
from odoo.tools import formatLang

_logger = logging.getLogger(__name__)

# Niveles de la cadencia = días de mora (de la factura más vencida) a los que
# se dispara cada paso. El orden importa: se escala de a un paso por vez.
COBRANZA_STAGES = [0, 5, 10, 15, 20]

STAGE_SELECTION = [
    ('0', 'Día 0 — Recordatorio (vencimiento)'),
    ('5', 'Día 5 — Seguimiento'),
    ('10', 'Día 10 — Ultimátum'),
    ('15', 'Día 15 — Llamada'),
    ('20', 'Día 20 — Visita'),
]


class ResPartner(models.Model):
    _inherit = 'res.partner'

    cobranza_exclude = fields.Boolean(
        string="Excluir de cobranza automática",
        default=False,
        help="Si está marcado, el cron de cobranza NUNCA le manda recordatorios "
             "a este cliente (ej: cuentas especiales, convenios, incobrables en "
             "gestión judicial).",
    )
    cobranza_last_stage = fields.Selection(
        STAGE_SELECTION,
        string="Último nivel de cobranza enviado",
        help="Hasta qué paso de la cadencia se le mandó al cliente. Se reinicia "
             "solo cuando el cliente cancela todo lo vencido.",
    )
    cobranza_last_action_date = fields.Date(
        string="Última acción de cobranza",
    )
    cobranza_anchor_due = fields.Date(
        string="Vencimiento ancla de la cadencia",
        help="Vencimiento de la factura MÁS vencida que disparó la cadencia "
             "actual. Mientras esa factura siga impaga, la cadencia avanza sobre "
             "ella (aunque venzan facturas nuevas: no se reinicia ni spamea). "
             "Si esa factura se cancela y queda otra deuda vencida, el ancla "
             "cambia y la cadencia arranca de nuevo desde el día 0.",
    )
    cobranza_action_ids = fields.One2many(
        'cristal.cobranza.action',
        'partner_id',
        string="Acciones de cobranza",
    )
    # ── Dashboard de deuda en tiempo real (pestaña Cobranza de la ficha) ──
    # Todos se calculan juntos en _compute_cobranza_dashboard (un solo snapshot).
    cobranza_currency_id = fields.Many2one(
        'res.currency', string="Moneda (cobranza)",
        compute='_compute_cobranza_dashboard')
    cobranza_total_vencido = fields.Monetary(
        string="Total vencido", currency_field='cobranza_currency_id',
        compute='_compute_cobranza_dashboard')
    cobranza_total_por_vencer = fields.Monetary(
        string="Por vencer (ventana)", currency_field='cobranza_currency_id',
        compute='_compute_cobranza_dashboard')
    cobranza_cant_vencidas = fields.Integer(
        string="Facturas vencidas", compute='_compute_cobranza_dashboard')
    cobranza_cant_por_vencer = fields.Integer(
        string="Facturas por vencer", compute='_compute_cobranza_dashboard')
    cobranza_dias_mora_max = fields.Integer(
        string="Días de mora (máx.)", compute='_compute_cobranza_dashboard')
    cobranza_gravedad = fields.Selection([
        ('critica', 'Crítica'),
        ('alta', 'Alta'),
        ('media', 'Media'),
        ('baja', 'Baja'),
        ('none', 'Sin deuda vencida'),
    ], string="Gravedad", compute='_compute_cobranza_dashboard')
    cobranza_overdue_move_ids = fields.Many2many(
        'account.move', string="Facturas vencidas (detalle)",
        compute='_compute_cobranza_dashboard')
    cobranza_upcoming_move_ids = fields.Many2many(
        'account.move', string="Por vencer (detalle)",
        compute='_compute_cobranza_dashboard')
    cobranza_total_vencido_display = fields.Char(
        string="Total vencido (autocompletar plantillas)",
        compute='_compute_cobranza_dashboard',
        help="Total vencido formateado (ej: '$ 81.336,00'). Autocompleta la "
             "variable {{2}} de las plantillas de cobranza (de tipo Campo), así "
             "el importe sale SIEMPRE del sistema y no de un valor a mano.",
    )

    @staticmethod
    def _cobranza_calc_gravedad(monto, dias):
        """Misma clasificación que el reporte de deudores por gravedad."""
        if monto <= 0:
            return 'none'
        if monto >= 150000 or dias >= 120:
            return 'critica'
        if monto >= 60000 or dias >= 60:
            return 'alta'
        if monto >= 20000 or dias >= 30:
            return 'media'
        return 'baja'

    def _compute_cobranza_dashboard(self):
        AccountMove = self.env['account.move']
        for partner in self:
            partner.cobranza_currency_id = partner._cobranza_currency()
            try:
                snap = partner.cobranza_snapshot()
            except Exception:  # noqa: BLE001 — nunca romper la lectura de la ficha
                snap = None
            if not snap:
                partner.cobranza_total_vencido = 0.0
                partner.cobranza_total_por_vencer = 0.0
                partner.cobranza_cant_vencidas = 0
                partner.cobranza_cant_por_vencer = 0
                partner.cobranza_dias_mora_max = 0
                partner.cobranza_gravedad = 'none'
                partner.cobranza_overdue_move_ids = AccountMove
                partner.cobranza_upcoming_move_ids = AccountMove
                partner.cobranza_total_vencido_display = \
                    partner.cobranza_format_amount(0.0)
                continue
            total_vencido = snap['total_vencido']
            partner.cobranza_total_vencido = total_vencido
            partner.cobranza_total_por_vencer = snap['total_por_vencer']
            partner.cobranza_cant_vencidas = snap['cant_vencidas']
            partner.cobranza_cant_por_vencer = snap['cant_por_vencer']
            partner.cobranza_dias_mora_max = snap['dias_mora_max']
            partner.cobranza_overdue_move_ids = snap['vencidas']
            partner.cobranza_upcoming_move_ids = snap['por_vencer']
            partner.cobranza_gravedad = partner._cobranza_calc_gravedad(
                total_vencido, snap['dias_mora_max'])
            partner.cobranza_total_vencido_display = \
                partner.cobranza_format_amount(total_vencido)

    # ────────────────────── Núcleo ──────────────────────
    def _cobranza_open_moves(self):
        """Facturas/notas de venta publicadas con saldo pendiente del cliente
        (consolidando contactos hijos bajo la entidad comercial)."""
        self.ensure_one()
        return self.env['account.move'].sudo().search([
            ('partner_id', 'child_of', self.commercial_partner_id.id),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('amount_residual', '>', 0),
        ], order='invoice_date_due asc, invoice_date asc')

    def _cobranza_overdue_moves(self, today=None):
        """Sólo las vencidas (usado por el reporte para embeber comprobantes)."""
        self.ensure_one()
        today = today or fields.Date.context_today(self)
        moves = self._cobranza_open_moves()
        return moves.filtered(
            lambda m: m.invoice_date_due and m.invoice_date_due < today
        )

    def cobranza_snapshot(self, ventana_dias=5, today=None):
        """Foto de la situación del cliente para la cobranza.

        Devuelve un dict con las facturas separadas en vencidas / por vencer,
        los totales y los días de mora de la más vieja.
        """
        self.ensure_one()
        today = today or fields.Date.context_today(self)
        moves = self._cobranza_open_moves()

        vencidas = moves.filtered(
            lambda m: m.invoice_date_due and m.invoice_date_due < today)
        limite = today + timedelta(days=ventana_dias)
        por_vencer = moves.filtered(
            lambda m: m.invoice_date_due and today <= m.invoice_date_due <= limite)

        # Neteo de notas de crédito: uso el residual CON SIGNO (las facturas
        # suman, las NC restan). Con amount_residual "a secas" (siempre positivo)
        # una NC de venta se contaría como deuda de más. Ej: factura $3.992 + NC
        # $3.200 → real $792, no $7.192.
        total_vencido = sum(vencidas.mapped('amount_residual_signed'))
        total_por_vencer = sum(por_vencer.mapped('amount_residual_signed'))

        # La mora y el vencimiento más antiguo se calculan SOLO sobre facturas
        # impagas (una nota de crédito no genera mora).
        vencidas_fact = vencidas.filtered(lambda m: m.move_type == 'out_invoice')
        por_vencer_fact = por_vencer.filtered(lambda m: m.move_type == 'out_invoice')
        if vencidas_fact:
            oldest_due = min(vencidas_fact.mapped('invoice_date_due'))
            dias_mora_max = (today - oldest_due).days
        else:
            oldest_due = False
            dias_mora_max = 0

        return {
            'today': today,
            'ventana_dias': ventana_dias,
            'vencidas': vencidas,
            'por_vencer': por_vencer,
            'total_vencido': total_vencido,
            'total_por_vencer': total_por_vencer,
            'total_adeudado': total_vencido + total_por_vencer,
            'oldest_due': oldest_due,
            'dias_mora_max': dias_mora_max,
            'cant_vencidas': len(vencidas_fact),
            'cant_por_vencer': len(por_vencer_fact),
        }

    # ────────────────────── Helpers de formato ──────────────────────
    def _cobranza_currency(self):
        self.ensure_one()
        return self.company_id.currency_id or self.env.company.currency_id

    def cobranza_format_amount(self, amount):
        """Formatea un importe en la moneda de la compañía (ej: '$ 81.336,00')."""
        self.ensure_one()
        return formatLang(
            self.env, amount, currency_obj=self._cobranza_currency())

    def _cobranza_billing_contact(self):
        """Contacto al que se le manda el recordatorio: la dirección de
        facturación de la entidad comercial. Si no tiene una definida,
        address_get devuelve la propia entidad comercial."""
        self.ensure_one()
        commercial = self.commercial_partner_id
        addr = commercial.address_get(['invoice'])
        contact = self.browse(addr.get('invoice')) if addr.get('invoice') else commercial
        return contact or commercial

    def cobranza_dias_mora(self, move, today=None):
        """Días de mora de una factura puntual (>=0)."""
        today = today or fields.Date.context_today(self)
        if not move.invoice_date_due:
            return 0
        return max((today - move.invoice_date_due).days, 0)
