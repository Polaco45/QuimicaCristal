import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MCPModelAccess(models.Model):
    _name = 'mcp.model.access'
    _description = 'MCP Model Access Control'
    _order = 'model_id'
    _rec_name = 'model_id'

    model_id = fields.Many2one(
        'ir.model', 'Modelo', required=True, ondelete='cascade',
        domain=[('transient', '=', False)],
    )
    model_name = fields.Char(related='model_id.model', store=True, readonly=True)
    active = fields.Boolean('Activo', default=True)
    perm_read = fields.Boolean('Lectura', default=True)
    perm_create = fields.Boolean('Crear', default=False)
    perm_write = fields.Boolean('Editar', default=False)
    perm_unlink = fields.Boolean('Eliminar', default=False)
    field_whitelist = fields.Text(
        'Campos permitidos',
        help='Lista de campos separados por coma. Dejar vacío para permitir todos. '
             'Ejemplo: name,email,phone,street',
    )
    max_records = fields.Integer(
        'Límite de registros',
        default=100,
        help='Máximo de registros por consulta (0 = sin límite)',
    )
    notes = fields.Text('Notas')

    _sql_constraints = [
        ('model_unique', 'UNIQUE(model_id)', 'Ya existe una configuración para este modelo.'),
    ]

    def get_allowed_fields(self):
        """Devuelve la lista de campos permitidos o None si todos están permitidos"""
        self.ensure_one()
        if not self.field_whitelist or not self.field_whitelist.strip():
            return None
        return [f.strip() for f in self.field_whitelist.split(',') if f.strip()]

    @api.model
    def get_access_for_model(self, model_name):
        """Buscar configuración de acceso para un modelo"""
        return self.sudo().search([
            ('model_name', '=', model_name),
            ('active', '=', True),
        ], limit=1)

    @api.model
    def get_all_enabled_models(self):
        """Devuelve todos los modelos habilitados"""
        return self.sudo().search([('active', '=', True)])
