import logging
from datetime import datetime, timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MCPPendingMessage(models.Model):
    """Cola de mensajes entrantes de WhatsApp que esperan respuesta.

    El cron `mcp_server.cron_refresh_pending_messages` mantiene esta cola
    actualizada: agrega mensajes inbound nuevos sin outbound posterior, y marca
    como `done` los que ya fueron respondidos.

    El tool `get_unanswered_messages` lee de acá para que un agente IA pueda
    consultar rápidamente qué conversaciones tiene pendientes sin escanear
    toda la base de mensajes en cada llamada.
    """

    _name = 'mcp.pending.message'
    _description = 'MCP Pending Message Queue'
    _order = 'last_inbound_at desc'
    _rec_name = 'channel_id'

    channel_id = fields.Many2one(
        'discuss.channel',
        'Canal',
        required=True,
        ondelete='cascade',
        index=True,
    )
    last_inbound_message_id = fields.Many2one(
        'mail.message',
        'Último mensaje entrante',
        ondelete='set null',
    )
    last_inbound_at = fields.Datetime(
        'Recibido el',
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        'Contacto',
        ondelete='set null',
        help='Autor del mensaje (puede ser un partner placeholder si es número desconocido)',
    )
    mobile_number = fields.Char(
        'Número WhatsApp',
        index=True,
    )
    wa_account_id = fields.Many2one(
        'whatsapp.account',
        'Cuenta de WhatsApp',
        ondelete='set null',
    )
    state = fields.Selection(
        [
            ('pending', 'Pendiente'),
            ('in_progress', 'En atención'),
            ('done', 'Atendido'),
            ('ignored', 'Ignorado'),
        ],
        'Estado',
        default='pending',
        required=True,
        index=True,
    )
    summary = fields.Text(
        'Resumen del mensaje',
        help='Cuerpo del último mensaje entrante (texto plano truncado)',
    )
    inbound_count = fields.Integer(
        '# Mensajes entrantes consecutivos',
        default=1,
        help='Cantidad de mensajes inbound consecutivos sin respuesta',
    )
    processed_at = fields.Datetime('Procesado el')
    notes = fields.Text('Notas internas')

    _sql_constraints = [
        ('channel_unique', 'UNIQUE(channel_id)',
         'Ya existe una entrada de cola para este canal.'),
    ]

    def action_mark_done(self):
        """Marcar como atendido manualmente"""
        self.write({
            'state': 'done',
            'processed_at': fields.Datetime.now(),
        })

    def action_mark_ignored(self):
        """Marcar como ignorado (mensaje no relevante o spam)"""
        self.write({
            'state': 'ignored',
            'processed_at': fields.Datetime.now(),
        })

    def action_mark_pending(self):
        """Volver a marcar como pendiente"""
        self.write({
            'state': 'pending',
            'processed_at': False,
        })

    @api.model
    def _get_lookback_window(self):
        """Cuántos días hacia atrás escanear mensajes inbound (default 30)"""
        param = self.env['ir.config_parameter'].sudo().get_param(
            'mcp_server.pending_lookback_days', '30'
        )
        try:
            return int(param)
        except (ValueError, TypeError):
            return 30

    @api.model
    def _refresh_queue(self):
        """Refrescar la cola de mensajes pendientes.

        Este método lo invoca el cron periódicamente. Su lógica es:
        1. Buscar mensajes entrantes de WhatsApp dentro de la ventana configurable.
        2. Por cada canal con un inbound, ver si hay un outbound posterior en el
           mismo canal.
        3. Si NO hay outbound posterior → asegurar entrada en cola con state=pending.
        4. Si SÍ hay outbound posterior → marcar entradas existentes como done.
        """
        WhatsappMessage = self.env['whatsapp.message'].sudo()
        MailMessage = self.env['mail.message'].sudo()

        days = self._get_lookback_window()
        since = fields.Datetime.now() - timedelta(days=days)

        inbound_msgs = WhatsappMessage.search([
            ('message_type', '=', 'inbound'),
            ('create_date', '>=', since),
        ], order='create_date desc')

        # Agrupar por canal (vía mail_message_id.res_id si el modelo es discuss.channel)
        seen_channels = set()
        for wa_msg in inbound_msgs:
            mail_msg = wa_msg.mail_message_id
            if not mail_msg or mail_msg.model != 'discuss.channel':
                continue
            channel_id = mail_msg.res_id
            if channel_id in seen_channels:
                continue
            seen_channels.add(channel_id)

            # ¿Hay un outbound posterior en este canal?
            later_outbound = MailMessage.search([
                ('model', '=', 'discuss.channel'),
                ('res_id', '=', channel_id),
                ('message_type', '=', 'whatsapp_message'),
                ('create_date', '>', mail_msg.create_date),
                # outbound = lo posteado por nosotros (no por el cliente)
                # Heurística: si tiene whatsapp.message asociada con message_type=outbound
            ], limit=1)

            has_outbound_later = False
            if later_outbound:
                # Verificar que ese mail.message tenga un whatsapp.message outbound
                later_wa = WhatsappMessage.search([
                    ('mail_message_id', 'in', later_outbound.ids),
                    ('message_type', '=', 'outbound'),
                ], limit=1)
                has_outbound_later = bool(later_wa)

            existing = self.search([('channel_id', '=', channel_id)], limit=1)

            if has_outbound_later:
                # Mensaje ya respondido → marcar entrada como done si existía
                if existing and existing.state in ('pending', 'in_progress'):
                    existing.write({
                        'state': 'done',
                        'processed_at': fields.Datetime.now(),
                    })
                continue

            # No respondido → asegurar entrada como pending
            body_text = self._strip_html(mail_msg.body or '')
            vals = {
                'channel_id': channel_id,
                'last_inbound_message_id': mail_msg.id,
                'last_inbound_at': mail_msg.create_date,
                'partner_id': mail_msg.author_id.id if mail_msg.author_id else False,
                'mobile_number': wa_msg.mobile_number,
                'wa_account_id': wa_msg.wa_account_id.id if wa_msg.wa_account_id else False,
                'summary': body_text[:500],
            }
            if existing:
                # Si la entrada ya está done/ignored y hay un mensaje nuevo, reabrirla
                if existing.last_inbound_message_id.id != mail_msg.id:
                    vals['state'] = 'pending'
                    vals['processed_at'] = False
                    vals['inbound_count'] = (existing.inbound_count or 0) + 1
                existing.write(vals)
            else:
                vals['state'] = 'pending'
                self.create(vals)

        return True

    @staticmethod
    def _strip_html(html):
        """Convertir HTML a texto plano de forma simple"""
        import re
        if not html:
            return ''
        text = re.sub(r'<br\s*/?>', '\n', html)
        text = re.sub(r'</p>', '\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'&amp;', '&', text)
        text = re.sub(r'&lt;', '<', text)
        text = re.sub(r'&gt;', '>', text)
        text = re.sub(r'&quot;', '"', text)
        return text.strip()
