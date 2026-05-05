import secrets
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MCPApiKey(models.Model):
    _name = 'mcp.api.key'
    _description = 'MCP API Key'
    _order = 'create_date desc'

    name = fields.Char('Nombre', required=True, default='Mi API Key')
    key = fields.Char(
        'API Key', required=True, readonly=True, copy=False,
        default=lambda self: secrets.token_urlsafe(32),
    )
    user_id = fields.Many2one(
        'res.users', 'Usuario Odoo', required=True,
        default=lambda self: self.env.user,
        help='Las operaciones MCP se ejecutarán con los permisos de este usuario.',
    )
    active = fields.Boolean('Activo', default=True)
    last_used = fields.Datetime('Último uso', readonly=True)
    request_count = fields.Integer('Solicitudes totales', readonly=True, default=0)
    notes = fields.Text('Notas')

    _sql_constraints = [
        ('key_unique', 'UNIQUE(key)', 'La API Key debe ser única.'),
    ]

    def action_regenerate_key(self):
        """Regenerar la API key"""
        for rec in self:
            rec.key = secrets.token_urlsafe(32)
        return True

    def _log_usage(self):
        """Registrar uso de la API key"""
        self.sudo().write({
            'last_used': fields.Datetime.now(),
            'request_count': self.request_count + 1,
        })
