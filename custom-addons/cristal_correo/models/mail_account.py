# -*- coding: utf-8 -*-
"""Casillas de correo de Ferozo leídas desde Odoo (IMAP)."""
import logging
import re


from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

FEROZO_IMAP = 'c2022041.ferozo.com'   # el mismo servidor que ya usa "Entrada ventas"
AUTOMATIC_SENDER = re.compile(
    r'(no-?reply|mailer-daemon|postmaster|bounce|notificacion|notification|notify|'
    r'alertas?@|newsletter|marketing@)', re.IGNORECASE)
OWN_DOMAINS = ('quimicacristal.com.ar', 'quimicacristal.odoo.com')

DEFAULT_AUTO_REPLY = (
    "<p>¡Hola! Recibimos tu mail y ya está en nuestra bandeja. Te respondemos a la "
    "brevedad en horario de atención (lunes a viernes de 8 a 13 y de 17 a 20 h, "
    "sábados de 9 a 13 h).</p><p>Química Cristal</p>")


class CristalMailAccount(models.Model):
    _name = 'cristal.mail.account'
    _description = "Cristal — Casilla de correo"
    _order = 'sequence, email'
    _rec_name = 'email'

    name = fields.Char(string="Nombre", required=True,
                       help="Cómo se ve la casilla en el panel (ej. Administración).")
    email = fields.Char(string="Dirección", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer()

    # ── Lectura IMAP (Ferozo) ──
    imap_host = fields.Char(string="Servidor IMAP", default=FEROZO_IMAP, required=True)
    imap_port = fields.Integer(string="Puerto", default=993, required=True)
    imap_ssl = fields.Boolean(string="SSL", default=True)
    password = fields.Char(
        string="Contraseña de la casilla", compute='_compute_password',
        inverse='_inverse_password', groups='base.group_system',
        help="La misma con la que se entra al webmail de Ferozo. Se guarda en el "
             "servidor de correo entrante de Odoo; este campo siempre se ve vacío.")
    fetchmail_server_id = fields.Many2one('fetchmail.server', string="Servidor de entrada",
                                          ondelete='set null', copy=False)
    last_fetch = fields.Datetime(related='fetchmail_server_id.date', string="Última lectura")
    last_error = fields.Char(string="Último error", copy=False)
    state = fields.Selection([
        ('no_password', 'Falta la contraseña'),
        ('ok', 'Conectada'),
        ('error', 'Con error'),
    ], string="Estado", compute='_compute_state')

    # ── Destino en Odoo (el alias que ya existe para la dirección) ──
    alias_id = fields.Many2one('mail.alias', string="Alias", compute='_compute_alias', store=True)
    destination_model = fields.Char(related='alias_id.alias_model_id.model',
                                    string="Modelo destino")
    project_id = fields.Many2one('project.project', string="Bandeja (proyecto)",
                                 compute='_compute_alias', store=True)
    destination = fields.Char(string="Destino", compute='_compute_destination')
    count_open = fields.Integer(string="Abiertos", compute='_compute_counts')
    count_today = fields.Integer(string="Hoy", compute='_compute_counts')

    # ── Respuesta automática ──
    auto_reply = fields.Boolean(
        string="Respuesta automática",
        help="Al entrar un mail nuevo (no una respuesta) se le contesta con el texto de "
             "abajo. Nunca a remitentes automáticos ni a direcciones propias.")
    auto_reply_body = fields.Html(string="Texto de la respuesta", default=DEFAULT_AUTO_REPLY)

    _sql_constraints = [('email_uniq', 'unique(email)', "Ya hay una casilla con esa dirección.")]

    # ─────────────────────────── computes ───────────────────────────
    def _compute_password(self):
        for rec in self:
            rec.password = False

    def _inverse_password(self):
        for rec in self:
            if rec.password:
                rec._ensure_fetchmail(password=rec.password.strip())

    @api.depends('email')
    def _compute_alias(self):
        Alias = self.env['mail.alias'].sudo()
        for rec in self:
            alias = Alias.browse()
            if rec.email and '@' in rec.email:
                local, domain = rec.email.strip().lower().split('@', 1)
                alias = Alias.search([('alias_name', '=', local),
                                      ('alias_domain_id.name', '=', domain)], limit=1)
            rec.alias_id = alias
            project = self.env['project.project']
            if alias and alias.alias_parent_model_id.model == 'project.project' \
                    and alias.alias_parent_thread_id:
                project = project.browse(alias.alias_parent_thread_id).exists()
            rec.project_id = project

    def _compute_destination(self):
        for rec in self:
            if rec.project_id:
                rec.destination = f"Tareas · {rec.project_id.name}"
            elif rec.destination_model == 'crm.lead':
                rec.destination = "Oportunidades (CRM)"
            elif rec.alias_id:
                rec.destination = rec.alias_id.alias_model_id.name
            else:
                rec.destination = "Sin alias: los mails van a la bandeja general"

    def _compute_state(self):
        for rec in self:
            server = rec.fetchmail_server_id.sudo()
            if not server or not server.password:
                rec.state = 'no_password'
            elif rec.last_error or server.state != 'done':
                rec.state = 'error'
            else:
                rec.state = 'ok'

    def _compute_counts(self):
        Task = self.env['project.task']
        today = fields.Datetime.to_string(fields.Datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0))
        for rec in self:
            if rec.project_id:
                base = [('project_id', '=', rec.project_id.id)]
                rec.count_open = Task.search_count(base + [('stage_id.fold', '=', False)])
                rec.count_today = Task.search_count(base + [('create_date', '>=', today)])
            else:
                rec.count_open = rec.count_today = 0

    # ─────────────────────────── servidor IMAP ───────────────────────────
    @property
    def email_formatted(self):
        # Sin codificar: Odoo arma el encabezado al enviar (formataddr dejaba =?utf-8?q?…).
        return f'"Química Cristal" <{(self.email or "").strip()}>'

    def _server_vals(self, password=None):
        self.ensure_one()
        vals = {
            'name': f"Correo · {self.email}",
            'server_type': 'imap',
            'server': self.imap_host,
            'port': self.imap_port,
            'is_ssl': self.imap_ssl,
            'user': self.email.strip(),
            'active': self.active,
        }
        # Si el mail no matchea ningún alias, que igual entre como tarea de la bandeja
        # de esta casilla (project_task.message_new la ubica por el servidor).
        if self.project_id:
            vals['object_id'] = self.env.ref('project.model_project_task').id
        if password:
            vals['password'] = password
        return vals

    def _ensure_fetchmail(self, password=None):
        Server = self.env['fetchmail.server'].sudo()
        for rec in self:
            server = rec.fetchmail_server_id
            if not server:
                server = Server.search([('user', '=ilike', rec.email.strip()),
                                        ('server_type', '=', 'imap')], limit=1)
            vals = rec._server_vals(password)
            if server:
                if server.state == 'done' and password:
                    server.set_draft()
                server.write(vals)
            else:
                server = Server.create(vals)
            rec.fetchmail_server_id = server
            if password:
                rec._confirm_login()

    def _confirm_login(self):
        for rec in self:
            try:
                rec.fetchmail_server_id.sudo().button_confirm_login()
                rec.last_error = False
            except Exception as e:  # UserError con el detalle del servidor
                rec.last_error = str(e)[:500]
                _logger.warning("Casilla %s: no conecta: %s", rec.email, e)

    def action_test(self):
        for rec in self:
            if not rec.fetchmail_server_id or not rec.fetchmail_server_id.password:
                raise UserError(_("Primero cargá la contraseña de %s.") % rec.email)
            server = rec.fetchmail_server_id.sudo()
            if server.state == 'done':
                server.set_draft()
            rec._confirm_login()
        return self._notify(_("Conexión probada"), self.last_error or _("Conecta bien."),
                            'danger' if self.last_error else 'success')

    def action_fetch(self):
        for rec in self:
            server = rec.fetchmail_server_id.sudo()
            if not server or server.state != 'done':
                raise UserError(_("La casilla %s no está conectada.") % rec.email)
            try:
                server.fetch_mail()
                rec.last_error = False
            except Exception as e:
                rec.last_error = str(e)[:500]
        return self._notify(_("Correo leído"), _("Listo: revisá la bandeja."), 'success')

    def action_open_inbox(self):
        self.ensure_one()
        if self.project_id:
            action = self.env['ir.actions.act_window']._for_xml_id('cristal_correo.action_bandeja')
            action['domain'] = [('project_id', '=', self.project_id.id)]
            action['context'] = {'default_project_id': self.project_id.id}
            action['name'] = f"Bandeja · {self.email}"
            return action
        if self.destination_model == 'crm.lead':
            action = self.env['ir.actions.act_window']._for_xml_id('crm.crm_lead_action_pipeline')
            action['name'] = f"Oportunidades · {self.email}"
            return action
        raise UserError(_("Esta casilla no tiene bandeja en Odoo."))

    @api.model
    def action_bandeja_all(self):
        """Bandeja unificada: los mails de todas las casillas con bandeja en Odoo."""
        projects = self.search([]).mapped('project_id')
        action = self.env['ir.actions.act_window']._for_xml_id('cristal_correo.action_bandeja')
        action['domain'] = [('project_id', 'in', projects.ids)]
        action['context'] = {'search_default_open_tasks': 1}
        return action

    @api.model
    def action_enviados(self):
        """Lo que se respondió desde las bandejas (mensajes de usuarios internos)."""
        projects = self.search([]).mapped('project_id')
        tasks = self.env['project.task'].search([('project_id', 'in', projects.ids)])
        return {
            'type': 'ir.actions.act_window', 'name': "Enviados",
            'res_model': 'mail.message', 'view_mode': 'list,form',
            'domain': [('model', '=', 'project.task'), ('res_id', 'in', tasks.ids),
                       ('message_type', '=', 'comment'),
                       ('subtype_id', '=', self.env.ref('mail.mt_comment').id),
                       ('author_id.user_ids', '!=', False)],
            'context': {'create': False},
        }

    def _notify(self, title, message, kind):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': title, 'message': message, 'type': kind, 'sticky': False}}

    # ─────────────────────────── helpers para tareas ───────────────────────────
    @api.model
    def _for_project(self, project):
        if not project:
            return self.browse()
        return self.search([('project_id', '=', project.id)], limit=1)

    @api.model
    def _is_automatic_sender(self, email_from):
        addr = (email_from or '').lower()
        return bool(AUTOMATIC_SENDER.search(addr)) or any(d in addr for d in OWN_DOMAINS)
