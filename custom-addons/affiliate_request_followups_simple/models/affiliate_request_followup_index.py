# models/affiliate_request_followup_index.py
from odoo import fields, models

class AffiliateRequest(models.Model):
    _inherit = "affiliate.request"

    # sin index=True (los índices los maneja init() con parciales)
    followup_12h_at = fields.Datetime(string="Seguimiento 12h", readonly=True)
    followup_24h_at = fields.Datetime(string="Seguimiento 24h", readonly=True)
    followup_48h_at = fields.Datetime(string="Seguimiento 48h", readonly=True)

    def init(self):
        # Índices parciales (IS NOT NULL)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS affiliate_request_fup12_notnull_idx
            ON affiliate_request (followup_12h_at)
            WHERE followup_12h_at IS NOT NULL
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS affiliate_request_fup24_notnull_idx
            ON affiliate_request (followup_24h_at)
            WHERE followup_24h_at IS NOT NULL
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS affiliate_request_fup48_notnull_idx
            ON affiliate_request (followup_48h_at)
            WHERE followup_48h_at IS NOT NULL
        """)

        # Limpiar posibles índices “auto” creados por index=True
        self.env.cr.execute("DROP INDEX IF EXISTS affiliate_request__followup_12h_at_index")
        self.env.cr.execute("DROP INDEX IF EXISTS affiliate_request__followup_24h_at_index")
        self.env.cr.execute("DROP INDEX IF EXISTS affiliate_request__followup_48h_at_index")

        # Ayuda al planner
        self.env.cr.execute("ANALYZE affiliate_request")
