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
    cobranza_action_ids = fields.One2many(
        'cristal.cobranza.action',
        'partner_id',
        string="Acciones de cobranza",
    )

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

        total_vencido = sum(vencidas.mapped('amount_residual'))
        total_por_vencer = sum(por_vencer.mapped('amount_residual'))

        if vencidas:
            oldest_due = min(vencidas.mapped('invoice_date_due'))
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
            'cant_vencidas': len(vencidas),
            'cant_por_vencer': len(por_vencer),
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

    def cobranza_dias_mora(self, move, today=None):
        """Días de mora de una factura puntual (>=0)."""
        today = today or fields.Date.context_today(self)
        if not move.invoice_date_due:
            return 0
        return max((today - move.invoice_date_due).days, 0)
