# -*- coding: utf-8 -*-
from odoo import fields, models

class AffiliateRequest(models.Model):
    _inherit = "affiliate.request"

    # Re-declaramos los campos para activar index=True (Odoo crea el índice BTREE)
    followup_12h_at = fields.Datetime(readonly=True, index=True)
    followup_24h_at = fields.Datetime(readonly=True, index=True)
    followup_48h_at = fields.Datetime(readonly=True, index=True)

    def init(self):
        """
        Creamos índices parciales (mucho más eficientes para WHERE ... IS NOT NULL).
        Se ejecuta en instalación/actualización/carga del registro.
        """
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS affiliate_request_fup12_notnull_idx
                ON affiliate_request (followup_12h_at)
                WHERE followup_12h_at IS NOT NULL;
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS affiliate_request_fup24_notnull_idx
                ON affiliate_request (followup_24h_at)
                WHERE followup_24h_at IS NOT NULL;
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS affiliate_request_fup48_notnull_idx
                ON affiliate_request (followup_48h_at)
                WHERE followup_48h_at IS NOT NULL;
        """)
