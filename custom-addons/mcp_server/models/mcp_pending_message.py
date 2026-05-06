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

    # Campos para tracking de notificación a Joaco
    notified_at = fields.Datetime(
        'Notificado a Joaco a las',
        help='Fecha en la que se le notificó a Joaco que este mensaje estaba pendiente.',
    )
    notification_skipped_reason = fields.Char(
        'Motivo de salto',
        help='Si la notificación se saltó por considerarse ruido, razón concreta.',
    )

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

    # ================================================================
    # NOTIFICACIÓN A JOACO (Fase C - Estructura 2)
    # ================================================================

    @api.model
    def _get_notification_config(self):
        """Devuelve la configuración del cron de notificación.
        Todos los valores son configurables via ir.config_parameter."""
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'target_number': ICP.get_param(
                'mcp_server.notify_target_number', '+5493585481191'),
            'wa_account_id': int(ICP.get_param(
                'mcp_server.notify_wa_account_id', '5')),
            'author_partner_id': int(ICP.get_param(
                'mcp_server.notify_author_partner_id', '80799')),
            'start_hour': int(ICP.get_param(
                'mcp_server.notify_start_hour', '8')),
            'start_minute': int(ICP.get_param(
                'mcp_server.notify_start_minute', '30')),
            'end_hour': int(ICP.get_param(
                'mcp_server.notify_end_hour', '21')),
            'end_minute': int(ICP.get_param(
                'mcp_server.notify_end_minute', '0')),
            'antispam_minutes': int(ICP.get_param(
                'mcp_server.notify_antispam_minutes', '30')),
            'enabled': ICP.get_param(
                'mcp_server.notify_enabled', 'True').lower() in ('true', '1', 'yes'),
        }

    @api.model
    def _is_in_notification_window(self, config):
        """¿Estamos en horario de notificación (Argentina time)?"""
        try:
            import pytz
            tz_ar = pytz.timezone('America/Argentina/Buenos_Aires')
            now_ar = datetime.now(tz_ar)
        except Exception:
            now_ar = datetime.utcnow()  # Fallback (UTC, no ideal pero no rompe)

        h, m = now_ar.hour, now_ar.minute
        start_h, start_m = config['start_hour'], config['start_minute']
        end_h, end_m = config['end_hour'], config['end_minute']

        if h < start_h or (h == start_h and m < start_m):
            return False
        if h > end_h or (h == end_h and m > end_m):
            return False
        return True

    @api.model
    def _classify_noise(self, pending):
        """Determina si un pending es 'ruido' (no notificar) o consulta real.

        Devuelve (is_noise: bool, reason: str|None).

        Reglas (en orden):
        1. Si el cuerpo arranca con un autorespond típico del cliente
           (bot de WhatsApp Business del otro lado) → ruido.
        2. Si tiene "?" o "¿" → NUNCA es ruido (consulta explícita).
        3. Si es largo (>30 chars sin emojis) → no ruido (contenido sustantivo).
        4. Si NO matchea patrón de cierre/agradecimiento → no ruido.
        5. Si nuestro último outbound tenía "?" y la respuesta es afirmativa
           corta → confirmación legítima, NO ruido.
        6. Si nuestro último outbound (template O texto libre) fue hace <24hs
           y la respuesta es cierre corto sin pregunta → ruido.
        7. Si no hay outbound previo cercano → no ruido (mejor avisar).
        """
        import re

        body = (pending.summary or '').strip()
        if not body:
            return (False, None)  # Mensaje vacío puede ser audio/imagen, mejor avisar

        # Strip emojis para medir longitud real
        emoji_re = re.compile(
            r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
            r'\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251'
            r'\u2600-\u27BF\u2700-\u27BF]+', flags=re.UNICODE,
        )
        body_clean = emoji_re.sub('', body).strip()
        body_lower = body_clean.lower()

        # 1. Autorespond del propio cliente (bot del otro lado)
        autorespond_starters = (
            'gracias por comunicarte', 'muchas gracias por comunicarte',
            'gracias por contactar', 'gracias por escribirnos',
            'fuera del horario', 'estamos fuera del horario',
            'te respondemos a la brevedad', 'te responderemos a la brevedad',
            'recibimos tu mensaje', 'le respondemos a la brevedad',
            '¿cómo podemos ayudarte', 'como podemos ayudarte',
        )
        for starter in autorespond_starters:
            if starter in body_lower:
                return (True, 'autorespond_del_cliente')

        # 2. Tiene signo de pregunta → nunca ruido
        if '?' in body or '¿' in body:
            return (False, None)

        # 3. Mensaje largo → contenido sustantivo, no ruido
        if len(body_clean) > 30:
            return (False, None)

        # 4. Patrón de cierre/agradecimiento (sin esto, no es ruido)
        closing_re = re.compile(
            r'^(gracias|graci[ai]s?|muchas\s+gracias|mil\s+gracias|'
            r'ok|oki|okey|oka|dale|dali|perfecto|listo|s[ií]|si|'
            r'b[áa]rbaro|ya|claro|buen[íi]simo|excelente|genial|'
            r'recibido|de\s*nada|tal\s*cual|pulgar|👍|🙏)'
            r'[\s\.\!\,\:¡!]*$',
            re.IGNORECASE,
        )
        if not closing_re.match(body_lower):
            return (False, None)  # No matchea cierre típico, mejor avisar

        # En este punto: cuerpo corto + sin pregunta + matchea cierre.
        # Para clasificar como ruido, queremos confirmar que la conversación
        # ya estaba activa (hubo outbound nuestro reciente) Y que ese outbound
        # NO era una pregunta esperando respuesta del cliente.
        WhatsappMessage = self.env['whatsapp.message'].sudo()
        MailMessage = self.env['mail.message'].sudo()

        last_inbound_at = pending.last_inbound_at
        if not last_inbound_at:
            return (False, None)

        # Buscar el último outbound nuestro en este canal en las últimas 24hs
        last_outbound_msg = MailMessage.search([
            ('model', '=', 'discuss.channel'),
            ('res_id', '=', pending.channel_id.id),
            ('message_type', '=', 'whatsapp_message'),
            ('create_date', '<', last_inbound_at),
            ('create_date', '>=', last_inbound_at - timedelta(hours=24)),
        ], order='create_date desc', limit=1)

        if not last_outbound_msg:
            # No hay outbound previo cercano → quizá conversación nueva
            # arrancada con cierre corto extraño. Mejor avisar.
            return (False, None)

        # ¿Ese último outbound era nuestro (whatsapp_message outbound)?
        last_outbound_wa = WhatsappMessage.search([
            ('mail_message_id', '=', last_outbound_msg.id),
            ('message_type', '=', 'outbound'),
        ], limit=1)
        if not last_outbound_wa:
            return (False, None)

        # 5. Si nuestro último mensaje era una pregunta, el cierre corto
        # del cliente puede ser una confirmación legítima → NO ruido.
        outbound_body_text = self._strip_html(last_outbound_msg.body or '')
        if '?' in outbound_body_text or '¿' in outbound_body_text:
            return (False, 'pregunta_pendiente_respondida')
            # Devuelvo False (no ruido) pero con razón informativa para
            # que se pueda auditar después.

        # 6. Outbound nuestro reciente sin pregunta + cierre corto → ruido.
        # Cubre tanto templates automáticos como respuestas manuales nuestras.
        if last_outbound_wa.wa_template_id:
            return (True, 'cierre_a_template_automatico')
        return (True, 'cierre_a_respuesta_manual')

    @api.model
    def _format_notification_text(self, pendings):
        """Arma el texto del WhatsApp que se le manda a Joaco."""
        n = len(pendings)
        if n == 0:
            return None

        plural = 's' if n > 1 else ''
        lines = [
            f"📨 Tenés {n} mensaje{plural} sin contestar en WhatsApp:",
            "",
        ]

        # Mostrar hasta los 5 más recientes
        for i, p in enumerate(pendings[:5]):
            partner = (p.partner_id.name if p.partner_id and p.partner_id.name
                       and p.partner_id.name != 'NADA' else 'Desconocido')
            mobile = p.mobile_number or '?'
            summary = (p.summary or '').strip().replace('\n', ' ')[:80]
            multi = f" (+{p.inbound_count - 1})" if p.inbound_count > 1 else ''
            lines.append(f"• {partner} ({mobile}){multi}")
            if summary:
                lines.append(f"  \"{summary}\"")

        if n > 5:
            lines.append("")
            lines.append(f"...y {n - 5} más.")

        lines.append("")
        lines.append("Decile a Claude \"leé los nuevos\" cuando estés.")

        return '\n'.join(lines)

    @api.model
    def _send_notification_to_joaco(self, body_text, config):
        """Envía el WhatsApp de aviso a Joaco usando el patrón estándar.

        Para encontrar el canal correcto en la cuenta WA destino, NO se puede
        filtrar discuss.channel por la cuenta (no hay relación directa). Se
        busca vía whatsapp.message: el último outbound o inbound desde/hacia
        ese número en esa cuenta.
        """
        WhatsappMessage = self.env['whatsapp.message'].sudo()
        MailMessage = self.env['mail.message'].sudo()

        # Normalizar número para Meta: solo dígitos
        target = config['target_number'].replace(' ', '').replace('-', '').replace('+', '')

        # Buscar el canal correcto vía último whatsapp.message en esta cuenta
        channel = self._find_channel_for_notification(target, config['wa_account_id'])

        if not channel:
            _logger.warning(
                "MCP notify: no se encontró canal WhatsApp para %s en cuenta %s. "
                "Hace falta una conversación previa con ese número en esa cuenta. "
                "Mandale un mensaje manualmente al menos una vez para abrir el canal.",
                target, config['wa_account_id']
            )
            return False

        # Convertir texto plano a HTML respetando saltos de línea
        body_html = '<p>' + body_text.replace('\n', '<br/>') + '</p>'

        try:
            mail_msg = MailMessage.create({
                'author_id': config['author_partner_id'],
                'body': body_html,
                'message_type': 'whatsapp_message',
                'model': 'discuss.channel',
                'res_id': channel.id,
                'subtype_id': 1,
            })

            wa_msg = WhatsappMessage.create({
                'mail_message_id': mail_msg.id,
                'message_type': 'outbound',
                'mobile_number': config['target_number'],
                'state': 'outgoing',
                'wa_account_id': config['wa_account_id'],
            })

            _logger.info(
                "MCP notify: aviso enviado a %s (canal=%s). mail_msg=%s, wa_msg=%s",
                config['target_number'], channel.id, mail_msg.id, wa_msg.id,
            )
            return True
        except Exception as e:
            _logger.exception("MCP notify: error enviando WhatsApp: %s", e)
            return False

    @api.model
    def _find_channel_for_notification(self, target_normalized, wa_account_id):
        """Encuentra el canal de WhatsApp correcto para enviar una notificación.

        Como discuss.channel no tiene campo wa_account_id directo, buscamos vía
        el último whatsapp.message (outbound o inbound) entre nosotros y ese
        número en esa cuenta — su mail_message_id apunta al canal correcto.
        """
        WhatsappMessage = self.env['whatsapp.message'].sudo()

        # Intentar primero con el último outbound (más confiable)
        last_outbound = WhatsappMessage.search([
            ('wa_account_id', '=', wa_account_id),
            ('message_type', '=', 'outbound'),
            ('mobile_number_formatted', '=', target_normalized),
        ], order='create_date desc', limit=1)

        if last_outbound and last_outbound.mail_message_id:
            mail_msg = last_outbound.mail_message_id
            if mail_msg.model == 'discuss.channel' and mail_msg.res_id:
                return self.env['discuss.channel'].browse(mail_msg.res_id).exists()

        # Fallback: último inbound desde ese número en esa cuenta
        last_inbound = WhatsappMessage.search([
            ('wa_account_id', '=', wa_account_id),
            ('message_type', '=', 'inbound'),
            ('mobile_number_formatted', '=', target_normalized),
        ], order='create_date desc', limit=1)

        if last_inbound and last_inbound.mail_message_id:
            mail_msg = last_inbound.mail_message_id
            if mail_msg.model == 'discuss.channel' and mail_msg.res_id:
                return self.env['discuss.channel'].browse(mail_msg.res_id).exists()

        return None

    @api.model
    def _run_notification_cron(self):
        """Cron principal: revisa pendientes, filtra ruido, notifica a Joaco si corresponde.

        Anti-spam: si en los últimos N minutos ya se notificó, no se vuelve
        a notificar a menos que haya pendientes NUEVOS no notificados todavía.

        Wrapper externo con try/except para que un error nunca rompa el cron
        en sí (que se desactivaría automáticamente en Odoo SH).
        """
        try:
            return self._run_notification_cron_inner()
        except Exception as e:
            _logger.exception(
                "MCP notify cron: error no atrapado, ignorando para no desactivar cron: %s", e
            )
            return False

    @api.model
    def _run_notification_cron_inner(self):
        """Lógica real del cron de notificación."""
        config = self._get_notification_config()

        if not config['enabled']:
            return False

        if not self._is_in_notification_window(config):
            _logger.debug("MCP notify: fuera de horario, skip")
            return False

        # Refrescar cola primero
        try:
            self._refresh_queue()
        except Exception:
            _logger.exception("MCP notify: error refrescando cola antes de notificar")

        # Buscar pendientes activos
        pendings = self.search([('state', '=', 'pending')],
                               order='last_inbound_at desc')

        if not pendings:
            _logger.debug("MCP notify: 0 pendientes")
            return False

        # Clasificar ruido vs real
        real_pendings = self.env['mcp.pending.message']
        for p in pendings:
            try:
                is_noise, reason = self._classify_noise(p)
            except Exception:
                _logger.exception("MCP notify: error clasificando pending %s", p.id)
                is_noise, reason = False, None

            if is_noise:
                if not p.notification_skipped_reason:
                    p.write({'notification_skipped_reason': reason})
                continue
            real_pendings |= p

        if not real_pendings:
            _logger.info("MCP notify: 0 pendientes después de filtrar ruido")
            return False

        # Filtrar los que no fueron notificados aún
        not_yet_notified = real_pendings.filtered(lambda r: not r.notified_at)

        # Anti-spam: ¿hace cuánto fue la última notificación?
        last_notified = self.search([
            ('notified_at', '!=', False),
        ], order='notified_at desc', limit=1)

        antispam_threshold = (datetime.now() -
                              timedelta(minutes=config['antispam_minutes']))

        if last_notified and last_notified.notified_at > antispam_threshold:
            # Estamos dentro de la ventana de antispam
            if not not_yet_notified:
                _logger.debug(
                    "MCP notify: skip por antispam (notificado hace <%d min)",
                    config['antispam_minutes'])
                return False
            # Hay pendientes nuevos no notificados → notificar SOLO esos
            to_notify = not_yet_notified
        else:
            # Fuera de la ventana antispam → notificar todos los pendientes reales
            to_notify = real_pendings

        # Armar el texto y enviar
        body_text = self._format_notification_text(to_notify)
        if not body_text:
            return False

        sent = self._send_notification_to_joaco(body_text, config)

        if sent:
            now = fields.Datetime.now()
            to_notify.write({'notified_at': now})
            _logger.info(
                "MCP notify: avisé a Joaco sobre %d pendientes (%s)",
                len(to_notify), to_notify.ids,
            )
            return True

        return False

