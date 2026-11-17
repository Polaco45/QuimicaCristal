from odoo import fields, models

INST_CHAINS = [
    ('kit', 'Después del kit (hasta la primera compra)'),
    ('reposicion', 'Después de la primera compra (hasta el segundo pedido)'),
    ('atraso', 'Recurrente que se atrasa'),
]

INST_CHANNELS = [
    ('whatsapp', 'WhatsApp'),
    ('llamada', 'Llamada'),
    ('visita', 'Visita'),
]


class CristalInstChainStep(models.Model):
    _name = 'cristal.inst.chain.step'
    _description = 'Institucional: paso de la cadena de avisos'
    _order = 'chain, sequence, id'

    name = fields.Char('Paso', required=True)
    chain = fields.Selection(INST_CHAINS, 'Cadena', required=True, index=True)
    sequence = fields.Integer('Orden', default=10, required=True)
    day = fields.Integer(
        'Día', required=True,
        help='Días contados desde el hecho que dispara la cadena: la entrega del kit, la primera compra '
             'o la fecha en que debía reponer.')
    channel = fields.Selection(INST_CHANNELS, 'Canal', required=True, default='whatsapp')
    message = fields.Text(
        'Mensaje',
        help='Texto del WhatsApp. Se puede usar {nombre} (quien decide) y {empresa}.')
    active = fields.Boolean('Activo', default=True)

    def render_message(self, partner):
        self.ensure_one()
        text = self.message or ''
        decisor = (partner.inst_decisor_id.name or '').strip()
        first = decisor.split(' ')[0] if decisor else ''
        text = text.replace('{nombre}', first).replace('{empresa}', partner.name or '')
        return text.replace('Hola ,', 'Hola,').replace('  ', ' ').strip()
