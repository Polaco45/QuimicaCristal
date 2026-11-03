# -*- coding: utf-8 -*-
"""Envío al proveedor por el canal de su ficha (WhatsApp con plantilla, o mail)."""
import base64
import logging
import re

from markupsafe import Markup

from odoo import _, api, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

PARAM_WA_ACCOUNT = 'cristal_compras.wa_account_id'      # cuenta de WhatsApp de Compras
PARAM_NOTIFY_USER = 'cristal_compras.notify_user_id'    # a quién le quedan los avisos
COMPRAS_EMAIL = '"Química Cristal · Compras" <compras@quimicacristal.com.ar>'
SERGIO_USER_ID = 2

# Cada envío: plantilla propia (Sergio) y, si no está aprobada, la que ya existe.
KINDS = {
    'order': {
        'templates': ['cristal_orden_compra', 'orden_de_compra_copy'],
        'report': 'purchase.action_report_purchase_order',
        'text': "Hola {name}, te paso un pedido. Muchas gracias.",
        'subject': "Pedido {ref} · Química Cristal",
        'legacy_free_text': "Te paso un pedido.",
    },
    'quote': {
        'templates': ['cristal_pedido_precio', 'solicitud_cotizacion_compra_copy'],
        'report': 'purchase.report_purchase_quotation',
        'text': "Hola {name}, ¿nos pasás precio y fecha de despacho de este pedido? Muchas gracias.",
        'subject': "Pedido de precio {ref} · Química Cristal",
        'legacy_free_text': "¿Nos pasás precio y fecha de despacho?",
    },
    'list': {
        'templates': ['cristal_pedido_lista'],
        'report': None,
        'text': "Hola {name}, ¿nos pasás la lista de precios actualizada? Muchas gracias.",
        'subject': "Lista de precios · Química Cristal",
    },
    'raw': {
        'templates': ['cristal_cotizar_materias_primas'],
        'report': 'cristal_compras.action_report_raw_materials',
        'text': ("Hola {name}, te paso el listado de materias primas que trabajamos para que "
                 "lo cotices. Muchas gracias."),
        'subject': "Materias primas para cotizar · Química Cristal",
    },
}

ALERT_WORDS = re.compile(
    r'(precio|\$|aument|subi|baj[oóa]|fecha|entreg|despach|demor|llega|plazo|condici|'
    r'pago|contado|transfer|cheque|stock|no ten|falta|sin\b|m[ií]nimo|flete|env[ií]o)',
    re.IGNORECASE)


class CristalCompras(models.AbstractModel):
    _name = 'cristal.compras'
    _description = "Cristal — agente de Compras"

    # ───────────────────────── Permisos y configuración ─────────────────────────
    @api.model
    def _check_ok(self):
        """Ningún mensaje a proveedores sale sin el OK de un responsable de Compras."""
        if not (self.env.su or self.env.user.has_group('purchase.group_purchase_manager')):
            raise AccessError(_("Solo un responsable de Compras puede mandar mensajes a proveedores."))

    @api.model
    def _wa_account(self):
        account_id = int(self.env['ir.config_parameter'].sudo().get_param(PARAM_WA_ACCOUNT) or 0)
        return self.env['whatsapp.account'].sudo().browse(account_id).exists()

    @api.model
    def _notify_user(self, record=None):
        user_id = int(self.env['ir.config_parameter'].sudo().get_param(PARAM_NOTIFY_USER) or 0)
        user = self.env['res.users'].sudo().browse(user_id).exists()
        if not user and record is not None and 'user_id' in record._fields:
            user = record.user_id
        return user or self.env['res.users'].sudo().browse(SERGIO_USER_ID).exists()

    @api.model
    def _template(self, kind, model):
        account = self._wa_account()
        if not account:
            return self.env['whatsapp.template']
        Template = self.env['whatsapp.template'].sudo()
        for name in KINDS[kind]['templates']:
            template = Template.search([('template_name', '=', name), ('status', '=', 'approved'),
                                        ('wa_account_id', '=', account.id),
                                        ('model_id.model', '=', model)], limit=1)
            if template:
                return template
        return Template

    @api.model
    def _channel(self, partner):
        """El canal de la ficha; si no se eligió: WhatsApp si tiene celular, si no mail."""
        channel = partner.cristal_buy_channel
        if not channel:
            channel = 'whatsapp' if (partner.mobile or partner.phone) else 'email'
        return channel

    # ───────────────────────── Envío ─────────────────────────
    @api.model
    def send(self, record, partner, kind):
        """Manda el mensaje ``kind`` al proveedor sobre ``record`` (orden o ficha).
        Queda registrado en el chatter de ``record``. Devuelve (ok, detalle)."""
        self._check_ok()
        spec = KINDS[kind]
        partner = partner.commercial_partner_id if not partner.mobile and not partner.email else partner
        name = (partner.name or '').split(' ')[0] if partner.is_company is False else partner.name
        text = spec['text'].format(name=name or partner.display_name)
        channel = self._channel(partner)
        ok, detail = False, ''
        if channel == 'whatsapp':
            ok, detail = self._send_whatsapp(record, partner, kind, text)
            if not ok and partner.email:
                why = detail
                ok, detail = self._send_email(record, partner, kind, text)
                detail = f"{detail} (WhatsApp no salió: {why})"
        else:
            ok, detail = self._send_email(record, partner, kind, text)
        if not ok:
            record.message_post(
                body=Markup("<p><b>No se le pudo mandar al proveedor</b>: %s</p><p>Texto: %s</p>")
                % (detail, text), message_type='comment', subtype_xmlid='mail.mt_note')
            self._alert(record, f"No salió el mensaje a {partner.display_name}: {detail}")
        return ok, detail

    @api.model
    def _send_whatsapp(self, record, partner, kind, text):
        template = self._template(kind, record._name)
        if not template:
            return False, "no hay plantilla de WhatsApp aprobada en la cuenta de Compras"
        mobile = partner.mobile or partner.phone
        if not mobile:
            return False, "el proveedor no tiene celular"
        vals = {
            'res_model': record._name,
            'res_ids': str(record.id),
            'wa_template_id': template.id,
            'phone': mobile,
        }
        # Las plantillas viejas (89/90) tienen un texto libre: va la frase de Sergio.
        free = template.variable_ids.filtered(lambda v: v.field_type == 'free_text' and v.line_type == 'body')
        if free:
            vals['free_text_1'] = KINDS[kind].get('legacy_free_text') or text
        try:
            with self.env.cr.savepoint():
                composer = self.env['whatsapp.composer'].sudo().with_context(
                    active_model=record._name, active_ids=[record.id], from_cristal_agent=True,
                ).create(vals)
                composer.action_send_whatsapp_template()
        except Exception as e:
            _logger.exception("cristal_compras: WhatsApp a %s falló", partner.display_name)
            return False, f"error de WhatsApp: {e}"
        return True, f"WhatsApp a {mobile} (plantilla {template.name})"

    @api.model
    def _send_email(self, record, partner, kind, text):
        if not partner.email:
            return False, "el proveedor no tiene mail ni celular cargado"
        spec = KINDS[kind]
        attachments = []
        if spec['report']:
            report = self.env.ref(spec['report'])
            pdf, _fmt = self.env['ir.actions.report'].sudo()._render_qweb_pdf(report, [record.id])
            filename = f"{(record.display_name or 'documento').replace('/', '-')}.pdf"
            attachments.append((filename, pdf))
        ref = getattr(record, 'name', '') or ''
        record.with_context(mail_post_autofollow=False).message_post(
            body=Markup("<p>%s</p>") % text,
            subject=spec['subject'].format(ref=ref),
            message_type='comment', subtype_xmlid='mail.mt_comment',
            partner_ids=partner.ids, email_from=COMPRAS_EMAIL,
            author_id=self.env.ref('base.partner_root').id,
            attachments=attachments)
        return True, f"mail a {partner.email}"

    # ───────────────────────── Avisos a Compras ─────────────────────────
    @api.model
    def _alert(self, record, summary, note=''):
        user = self._notify_user(record)
        if not user:
            return
        record.sudo().activity_schedule(
            'mail.mail_activity_data_todo', user_id=user.id,
            summary=summary[:120], note=note or summary)

    # ───────────────────────── Lo que llega de proveedores ─────────────────────────
    @api.model
    def _is_price_list(self, attachment, text):
        name = (attachment.name or '').lower()
        mimetype = attachment.mimetype or ''
        if name.endswith(('.xls', '.xlsx', '.ods', '.csv')) or 'spreadsheet' in mimetype or 'excel' in mimetype:
            return True
        hint = f"{name} {text or ''}".lower()
        return any(w in hint for w in ('lista', 'precio', 'listado', 'cotiz'))

    @api.model
    def _open_order(self, partner):
        return self.env['purchase.order'].sudo().search([
            ('partner_id', 'child_of', partner.commercial_partner_id.id),
            ('state', 'in', ['sent', 'to approve', 'purchase']),
            ('cristal_supplier_msg_date', '!=', False),
        ], order='cristal_supplier_msg_date desc', limit=1)

    @api.model
    def process_supplier_message(self, partner, message, source, order=None):
        """Mensaje de un proveedor (WhatsApp o mail): guarda las listas, deja la respuesta
        en la orden abierta y avisa a Compras si habla de precio, fecha o condiciones."""
        partner = partner.commercial_partner_id
        if not partner or partner.supplier_rank <= 0:
            return False
        text = Markup(message.body or '').striptags().strip() if message.body else ''
        PriceList = self.env['cristal.compras.price.list'].sudo()
        saved = PriceList
        for attachment in message.attachment_ids:
            if self._is_price_list(attachment, f"{message.subject or ''} {text}"):
                saved |= PriceList.register(partner, attachment, source)
        order = order or self._open_order(partner)
        if order and message.model != 'purchase.order':
            order.sudo().message_post(
                body=Markup("<p><b>Respuesta del proveedor por %s:</b></p><p>%s</p>")
                % ('WhatsApp' if source == 'whatsapp' else 'mail', text or '(adjunto)'),
                message_type='comment', subtype_xmlid='mail.mt_note',
                attachment_ids=message.attachment_ids.ids)
        target = order or partner
        if saved:
            self._alert(target, f"Lista de precios de {partner.name}",
                        f"Llegó por {source}: {', '.join(saved.mapped('name'))}. Está en Compras → "
                        "Listas de precios recibidas para subirla al Drive y cargarla.")
        elif text and ALERT_WORDS.search(text):
            self._alert(target, f"{partner.name} respondió: revisá precio, fecha o condiciones",
                        text[:500])
        return True

    # ───────────────────────── Plantillas (cuando se conecte el número de Compras) ─────────────────────────
    @api.model
    def setup_whatsapp_templates(self, account_id):
        """Crea en borrador las plantillas de Compras en la cuenta ``account_id`` y la deja como
        cuenta de Compras. Después hay que mandarlas a aprobar a Meta desde cada plantilla."""
        self._check_ok()
        account = self.env['whatsapp.account'].sudo().browse(int(account_id)).exists()
        if not account:
            raise AccessError(_("No existe esa cuenta de WhatsApp."))
        Template = self.env['whatsapp.template'].sudo()
        Model = self.env['ir.model'].sudo()
        specs = [
            ('cristal_orden_compra', "Compras · Orden de compra", 'purchase.order', 'order'),
            ('cristal_pedido_precio', "Compras · Pedido de precio", 'purchase.order', 'quote'),
            ('cristal_pedido_lista', "Compras · Pedido de lista", 'res.partner', 'list'),
            ('cristal_cotizar_materias_primas', "Compras · Materias primas para cotizar", 'res.partner', 'raw'),
        ]
        created = Template
        for template_name, label, model, kind in specs:
            if Template.search_count([('template_name', '=', template_name), ('wa_account_id', '=', account.id)]):
                continue
            spec = KINDS[kind]
            on_order = model == 'purchase.order'
            vals = {
                'name': label,
                'template_name': template_name,
                'wa_account_id': account.id,
                'model_id': Model._get_id(model),
                'lang_code': 'es',
                'template_type': 'utility',
                'phone_field': 'partner_id.mobile' if on_order else 'mobile',
                'body': spec['text'].replace('{name}', '{{1}}'),
                'variable_ids': [(0, 0, {
                    'name': '{{1}}', 'line_type': 'body', 'field_type': 'field',
                    'field_name': 'partner_id.name' if on_order else 'name', 'demo_value': 'Juan'})],
            }
            if spec['report']:
                vals.update({'header_type': 'document', 'report_id': self.env.ref(spec['report']).id})
            created |= Template.create(vals)
        self.env['ir.config_parameter'].sudo().set_param(PARAM_WA_ACCOUNT, account.id)
        return created.ids
