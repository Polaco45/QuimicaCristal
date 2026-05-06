import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MCPReportAccess(models.Model):
    """Whitelist de reportes permitidos para ser ejecutados via MCP.

    Solo los reportes registrados acá (y activos) pueden ser invocados con la
    herramienta `generate_report`. Esto evita que un agente IA pueda ejecutar
    cualquier reporte arbitrario del sistema.
    """

    _name = 'mcp.report.access'
    _description = 'MCP Report Access Control'
    _order = 'name'
    _rec_name = 'name'

    name = fields.Char(
        'Nombre interno',
        required=True,
        help='Nombre amigable para identificar el reporte (ej: "Lista de precios mayorista")',
    )
    report_id = fields.Many2one(
        'ir.actions.report',
        'Reporte',
        required=True,
        ondelete='cascade',
        help='Reporte de Odoo que se permitirá ejecutar via MCP',
    )
    report_xml_id = fields.Char(
        'XML ID',
        compute='_compute_report_xml_id',
        store=True,
        readonly=True,
        help='Referencia técnica del reporte (ej: product.action_report_pricelist)',
    )
    model_name = fields.Char(
        related='report_id.model',
        store=True,
        readonly=True,
        string='Modelo destino',
    )
    active = fields.Boolean('Activo', default=True)
    description = fields.Text(
        'Descripción',
        help='Descripción de uso del reporte y cuándo conviene utilizarlo',
    )
    default_data = fields.Text(
        'Datos por defecto (JSON)',
        help='JSON con parámetros por defecto que se pasarán al reporte si no se '
             'envían explícitamente en la llamada. Ejemplo: {"pricelist_id": 6}',
    )

    _sql_constraints = [
        ('report_unique', 'UNIQUE(report_id)',
         'Ya existe una configuración para este reporte.'),
    ]

    @api.depends('report_id')
    def _compute_report_xml_id(self):
        """Resolver el xml_id del reporte"""
        for rec in self:
            if not rec.report_id:
                rec.report_xml_id = False
                continue
            xml_ids = rec.report_id.get_external_id()
            rec.report_xml_id = xml_ids.get(rec.report_id.id) or False

    @api.model
    def get_access_for_xml_id(self, xml_id):
        """Buscar configuración de un reporte por su xml_id"""
        return self.sudo().search([
            ('report_xml_id', '=', xml_id),
            ('active', '=', True),
        ], limit=1)

    @api.model
    def get_access_for_report_id(self, report_id):
        """Buscar configuración de un reporte por su ID numérico"""
        return self.sudo().search([
            ('report_id', '=', report_id),
            ('active', '=', True),
        ], limit=1)

    @api.model
    def get_all_enabled_reports(self):
        """Devuelve todos los reportes habilitados"""
        return self.sudo().search([('active', '=', True)])
