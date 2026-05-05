from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mcp_server_enabled = fields.Boolean(
        'MCP Server Habilitado',
        config_parameter='mcp_server.enabled',
        default=True,
    )
    mcp_max_records_global = fields.Integer(
        'Límite global de registros',
        config_parameter='mcp_server.max_records_global',
        default=200,
        help='Máximo de registros por consulta si no hay límite en el modelo.',
    )
    mcp_log_requests = fields.Boolean(
        'Registrar solicitudes',
        config_parameter='mcp_server.log_requests',
        default=True,
        help='Registrar todas las solicitudes MCP en el log del servidor.',
    )
