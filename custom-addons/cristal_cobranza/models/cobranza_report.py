# -*- coding: utf-8 -*-
"""Reporte general de deuda — el equivalente "a gran escala" del dashboard de la
ficha: una fila por cliente (entidad comercial) con su total vencido, por vencer,
mora y gravedad.

Se implementa como VISTA SQL (_auto = False) y no con campos computados a propósito:
una vista SQL resuelve todos los clientes en una sola consulta y permite filtrar,
agrupar y ordenar por gravedad / monto / mora (cosa que los campos computados no
almacenados de la ficha no permiten).

La clasificación de gravedad es la MISMA que la del dashboard de la ficha y la del
reporte de deudores (ver res_partner._cobranza_calc_gravedad):
    CRÍTICA = +$150.000 o +120 días · ALTA = +$60.000 o +60 días
    MEDIA   = +$20.000  o +30 días  · BAJA = resto
"""
from odoo import models, fields, tools

from .res_partner import STAGE_SELECTION

GRAVEDAD_SELECTION = [
    ('critica', 'Crítica'),
    ('alta', 'Alta'),
    ('media', 'Media'),
    ('baja', 'Baja'),
    ('none', 'Sin deuda vencida'),
]


class CristalCobranzaReport(models.Model):
    _name = 'cristal.cobranza.report'
    _description = "Cristal Cobranza — Reporte general de deuda"
    _auto = False
    _rec_name = 'partner_id'
    _order = 'total_vencido desc'

    partner_id = fields.Many2one('res.partner', string="Cliente", readonly=True)
    currency_id = fields.Many2one('res.currency', string="Moneda", readonly=True)

    total_vencido = fields.Monetary(string="Total vencido", readonly=True)
    total_por_vencer = fields.Monetary(string="Por vencer", readonly=True)
    total_adeudado = fields.Monetary(string="Total adeudado", readonly=True)

    cant_vencidas = fields.Integer(string="Facturas vencidas", readonly=True)
    cant_por_vencer = fields.Integer(string="Facturas por vencer", readonly=True)
    dias_mora_max = fields.Integer(string="Días de mora (máx.)", readonly=True)
    oldest_due = fields.Date(string="Vencimiento más antiguo", readonly=True)

    gravedad = fields.Selection(
        GRAVEDAD_SELECTION, string="Gravedad", readonly=True)
    cobranza_exclude = fields.Boolean(
        string="Excluido de cobranza", readonly=True)
    cobranza_last_stage = fields.Selection(
        STAGE_SELECTION, string="Último nivel enviado", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    t.partner_id AS id,
                    t.partner_id,
                    t.currency_id,
                    t.total_vencido,
                    t.total_por_vencer,
                    t.total_vencido + t.total_por_vencer AS total_adeudado,
                    t.cant_vencidas,
                    t.cant_por_vencer,
                    t.dias_mora_max,
                    t.oldest_due,
                    t.cobranza_exclude,
                    t.cobranza_last_stage,
                    CASE
                        WHEN t.total_vencido <= 0 THEN 'none'
                        WHEN t.total_vencido >= 150000
                          OR t.dias_mora_max >= 120 THEN 'critica'
                        WHEN t.total_vencido >= 60000
                          OR t.dias_mora_max >= 60 THEN 'alta'
                        WHEN t.total_vencido >= 20000
                          OR t.dias_mora_max >= 30 THEN 'media'
                        ELSE 'baja'
                    END AS gravedad
                FROM (
                    SELECT
                        am.commercial_partner_id AS partner_id,
                        MIN(am.currency_id) AS currency_id,
                        COALESCE(SUM(CASE WHEN am.invoice_date_due < CURRENT_DATE
                                          THEN am.amount_residual_signed ELSE 0 END), 0)
                            AS total_vencido,
                        COALESCE(SUM(CASE WHEN am.invoice_date_due >= CURRENT_DATE
                                          THEN am.amount_residual_signed ELSE 0 END), 0)
                            AS total_por_vencer,
                        COUNT(CASE WHEN am.invoice_date_due < CURRENT_DATE
                                   AND am.move_type = 'out_invoice'
                                   THEN 1 END) AS cant_vencidas,
                        COUNT(CASE WHEN am.invoice_date_due >= CURRENT_DATE
                                   AND am.move_type = 'out_invoice'
                                   THEN 1 END) AS cant_por_vencer,
                        COALESCE(MAX(CASE WHEN am.invoice_date_due < CURRENT_DATE
                                          AND am.move_type = 'out_invoice'
                                          THEN (CURRENT_DATE - am.invoice_date_due)
                                          ELSE 0 END), 0) AS dias_mora_max,
                        MIN(CASE WHEN am.invoice_date_due < CURRENT_DATE
                                 AND am.move_type = 'out_invoice'
                                 THEN am.invoice_date_due END) AS oldest_due,
                        bool_or(COALESCE(rp.cobranza_exclude, FALSE))
                            AS cobranza_exclude,
                        MIN(rp.cobranza_last_stage) AS cobranza_last_stage
                    FROM account_move am
                    JOIN res_partner rp ON rp.id = am.commercial_partner_id
                    WHERE am.move_type IN ('out_invoice', 'out_refund')
                      AND am.state = 'posted'
                      AND am.payment_state IN ('not_paid', 'partial')
                      AND am.amount_residual > 0
                      AND am.invoice_date_due IS NOT NULL
                    GROUP BY am.commercial_partner_id
                ) t
            )
        """ % (self._table,))
