# -*- coding: utf-8 -*-
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CristalFidFlow(models.Model):
    _name = 'cristal.fid.flow'
    _description = 'Fidelización — flujo automático'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    code = fields.Char(required=True, readonly=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Qué hace')
    category = fields.Selection([('utility', 'Servicio (ligado a una compra)'),
                                 ('marketing', 'Promoción')], required=True,
                                help='Las promociones solo van a quien aceptó recibirlas.')
    send_enabled = fields.Boolean(string='Enviar de verdad',
                                  help='Apagado: el flujo corre en modo prueba y solo registra a quién '
                                       'le habría escrito. Prenderlo recién con la plantilla aprobada.')
    holdout_pct = fields.Integer(string='Grupo de control (%)', default=10,
                                 help='Porcentaje de clientes que no reciben el mensaje, para medir '
                                      'cuánto suma el flujo de verdad.')
    daily_limit = fields.Integer(string='Máximo por día', default=40)
    wa_account_id = fields.Many2one('whatsapp.account', string='Cuenta de WhatsApp')
    template_id = fields.Many2one('whatsapp.template', string='Plantilla')
    template_status = fields.Selection(related='template_id.status', string='Estado en Meta')
    template_body = fields.Text(string='Texto de la plantilla',
                                help='{{1}} es el nombre del cliente; las demás variables las completa el flujo.')
    button_texts = fields.Char(string='Botones', help='Respuestas rápidas separadas por |. '
                                                      'La primera es la respuesta positiva; '
                                                      'la última, si dice "no me", es la baja.')
    offer_text = fields.Char(string='Beneficio que ofrece', help='Se inserta en el mensaje (si aplica).')
    responsible_user_id = fields.Many2one('res.users', string='Responsable de las respuestas',
                                          help='Recibe la tarea cuando un cliente responde mal o pide pedido.')
    touch_ids = fields.One2many('cristal.fid.touch', 'flow_id')
    touch_count = fields.Integer(compute='_compute_stats')
    conversion_rate = fields.Float(string='Conversión (%)', compute='_compute_stats')
    holdout_rate = fields.Float(string='Conversión control (%)', compute='_compute_stats')

    _sql_constraints = [('code_uniq', 'unique(code)', 'El código del flujo es único.')]

    def _compute_stats(self):
        Touch = self.env['cristal.fid.touch']
        for flow in self:
            touches = Touch.search([('flow_id', '=', flow.id)])
            reached = touches.filtered(lambda t: t.state in ('sent', 'dry_run'))
            control = touches.filtered(lambda t: t.state == 'holdout')
            flow.touch_count = len(touches)
            flow.conversion_rate = 100.0 * len(reached.filtered('converted')) / len(reached) if reached else 0.0
            flow.holdout_rate = 100.0 * len(control.filtered('converted')) / len(control) if control else 0.0

    def buttons(self):
        self.ensure_one()
        return [b.strip() for b in (self.button_texts or '').split('|') if b.strip()]

    # ── Plantilla de WhatsApp ──────────────────────────────────────
    def action_create_template(self):
        """Crea la plantilla en borrador en Odoo (no la manda a Meta)."""
        Template = self.env['whatsapp.template'].sudo()
        partner_model = self.env['ir.model']._get('res.partner')
        for flow in self:
            if flow.template_id:
                continue
            if not (flow.wa_account_id and flow.template_body):
                raise UserError(_("Falta la cuenta de WhatsApp o el texto de %s.", flow.name))
            body = flow.template_body
            n_vars = len(set(re.findall(r'\{\{(\d+)\}\}', body)))
            # Todas texto libre: {{1}} es el nombre de pila (lo arma el motor), no el
            # nombre completo del contacto ("Hola Oscar", no "Hola Giordano, Oscar Rafael").
            variables = [(0, 0, {'name': '{{%s}}' % i, 'line_type': 'body', 'field_type': 'free_text',
                                 'demo_value': 'Ana' if i == 1 else 'la lavandina'})
                         for i in range(1, n_vars + 1)]
            template = Template.create({
                'name': flow.name,
                'template_name': 'cristal_%s' % flow.code,
                'wa_account_id': flow.wa_account_id.id,
                'model_id': partner_model.id,
                'phone_field': 'mobile',
                'lang_code': 'es_AR' if 'es_AR' in dict(Template._fields['lang_code'].selection) else 'es',
                'template_type': flow.category,
                'body': body,
                'button_ids': [(0, 0, {'name': b, 'button_type': 'quick_reply', 'sequence': i})
                               for i, b in enumerate(flow.buttons())],
            })
            # Odoo genera variables solas desde el texto: se reemplazan por las nuestras.
            template.write({'variable_ids': [(5, 0, 0)] + variables})
            flow.template_id = template

    def action_submit_template(self):
        """Manda la plantilla a aprobación de Meta."""
        for flow in self.filtered('template_id'):
            flow.template_id.button_submit_template()

    def action_run_now(self):
        self.env['cristal.fid.engine']._cron_run(flows=self)
        return {'type': 'ir.actions.client', 'tag': 'reload'}
