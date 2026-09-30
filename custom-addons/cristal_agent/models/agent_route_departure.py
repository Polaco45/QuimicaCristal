# -*- coding: utf-8 -*-
"""
Salidas de la ruta del camión — un registro por jueves de cada circuito.

Las salidas NO se calculan al vuelo: se generan como registros (`generate_upcoming`)
para poder darles estado (preventa / rescate / confirmada / postergada / realizada),
postergarlas (cambiar la fecha), activar el Plan B (rescate: envío gratis desde
$75.000 + producto de cortesía) y acumular el monto de preventa.

Comunicación (plantillas de WhatsApp de la cuenta Crilimp, pendientes de Meta):
- ruta_aviso_paso / ruta_rescate: se disparan A MANO desde la salida, en tandas de 25.
- ruta_confirmacion_entrega (T-1), ruta_proxima_pasada (T+1): crons, creados
  INACTIVOS hasta que Meta apruebe las plantillas.
- ruta_salida_reprogramada: a mano, al postergar.
"""
import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEFAULT_TZ = 'America/Argentina/Cordoba'
BATCH_SIZE = 25
# El rescate (Plan B) cierra el miércoles a las 12 h: así lo dice la plantilla
# 'ruta_rescate' ("Si nos confirma hasta mañana miércoles a las 12 h").
RESCUE_CUTOFF_DAYS_BEFORE = 1
RESCUE_CUTOFF_HOUR = 12
DEFAULT_PAYMENT_TEXT = 'transferencia anticipada o efectivo contra entrega'


def _fmt_money(value):
    return '${:,.0f}'.format(value or 0).replace(',', '.')


def _ddmm(d):
    return d.strftime('%d/%m') if d else ''


class CristalAgentRouteDeparture(models.Model):
    _name = 'cristal.agent.route.departure'
    _description = 'Salida de la ruta del camión'
    _order = 'date, circuit_id'

    name = fields.Char(compute='_compute_name', store=True)
    circuit_id = fields.Many2one(
        'cristal.agent.circuit', required=True, ondelete='cascade', index=True)
    date = fields.Date(string="Fecha de salida (jueves)", required=True, index=True)
    original_date = fields.Date(
        string="Fecha original", readonly=True, copy=False,
        help="Se completa sola la primera vez que se cambia la fecha (postergación).")
    state = fields.Selection([
        ('preventa', 'Preventa'),
        ('rescate', 'Rescate (Plan B)'),
        ('confirmada', 'Confirmada'),
        ('postergada', 'Postergada'),
        ('realizada', 'Realizada'),
    ], default='preventa', required=True, index=True)
    rescue_free_shipping_from = fields.Float(
        string="Envío gratis desde (rescate)", default=75000.0,
        help="Cuando la salida está en rescate, el envío es gratis desde este monto.")
    courtesy_product_id = fields.Many2one(
        'product.product', string="Producto de cortesía (rescate)",
        help="Producto que el bot ofrece como cortesía cuando la salida está en rescate.")
    preventa_amount = fields.Float(
        string="Monto de preventa", compute='_compute_preventa_amount',
        help="Suma de subtotales de productos (sin IVA ni flete) de las órdenes de esta salida.")
    order_ids = fields.One2many(
        'sale.order', 'route_departure_id', string="Órdenes")
    aviso_partner_ids = fields.Many2many(
        'res.partner', 'cristal_route_dep_aviso_rel', 'departure_id', 'partner_id',
        string="Avisados (aviso de paso)", copy=False)
    rescate_partner_ids = fields.Many2many(
        'res.partner', 'cristal_route_dep_rescate_rel', 'departure_id', 'partner_id',
        string="Avisados (rescate)", copy=False)

    _sql_constraints = [
        ('circuit_date_uniq', 'unique(circuit_id, date)',
         'Ya existe una salida para ese circuito y esa fecha.'),
    ]

    @api.depends('circuit_id', 'date')
    def _compute_name(self):
        for dep in self:
            c = dep.circuit_id.name or 'Circuito'
            dep.name = f"{c} — {_ddmm(dep.date)}" if dep.date else c

    @api.depends('order_ids.order_line.price_subtotal',
                 'order_ids.order_line.product_id')
    def _compute_preventa_amount(self):
        config = self.env['cristal.agent.config'].sudo().get_active()
        freight_id = config.route_freight_product_id.id if (
            config and config.route_freight_product_id) else False
        for dep in self:
            total = 0.0
            for order in dep.order_ids.filtered(lambda o: o.state != 'cancel'):
                for line in order.order_line:
                    if freight_id and line.product_id.id == freight_id:
                        continue
                    total += line.price_subtotal
            dep.preventa_amount = total

    def write(self, vals):
        # Postergar = cambiarle la fecha al registro. Guardamos la fecha original la
        # primera vez (la usa la plantilla de salida reprogramada).
        if 'date' in vals:
            for dep in self:
                if not dep.original_date and dep.date and \
                        str(dep.date) != str(vals['date']):
                    dep.original_date = dep.date
        return super().write(vals)

    # ───────────────────────── Fechas (hora Córdoba → UTC) ─────────────────────────
    def _tz(self):
        config = self.env['cristal.agent.config'].sudo().get_active()
        return pytz.timezone(config.timezone if config and config.timezone else DEFAULT_TZ)

    def _local_to_utc(self, day, hour_float):
        hour = int(hour_float)
        minute = int(round((hour_float - hour) * 60))
        local_dt = self._tz().localize(datetime.combine(day, time(hour, minute)))
        return local_dt.astimezone(pytz.utc).replace(tzinfo=None)

    def _local_today(self):
        return datetime.now(self._tz()).date()

    def get_preventa_cutoff(self):
        """Cierre para tomar pedidos de esta salida, como datetime naive UTC.
        - Preventa: el martes (config) a las 18:00 hora Córdoba previo a la salida.
        - Rescate: el miércoles a las 12:00 (lo que promete la plantilla de rescate)."""
        self.ensure_one()
        if self.state == 'rescate':
            day = self.date - timedelta(days=RESCUE_CUTOFF_DAYS_BEFORE)
            return self._local_to_utc(day, RESCUE_CUTOFF_HOUR)
        config = self.env['cristal.agent.config'].sudo().get_active()
        # Sin `or default`: lunes = 0 y medianoche = 0.0 son valores válidos.
        cutoff_weekday = int(config.route_preventa_cutoff_weekday) % 7 if config else 1
        cutoff_hour = float(config.route_preventa_cutoff_hour) if config else 18.0
        day = self.date - timedelta(days=1)
        while day.weekday() != cutoff_weekday:
            day -= timedelta(days=1)
        return self._local_to_utc(day, cutoff_hour)

    def get_commitment_datetime(self):
        """Entrega comprometida: el jueves de la salida a las 09:00 hora Córdoba
        (repartimos por la mañana), como datetime naive UTC."""
        self.ensure_one()
        return self._local_to_utc(self.date, 9.0)

    def get_cutoff_local(self):
        """Cierre en hora Córdoba (datetime aware), para mostrar."""
        self.ensure_one()
        return pytz.utc.localize(self.get_preventa_cutoff()).astimezone(self._tz())

    # ───────────────────────── Generación ─────────────────────────
    @api.model
    def generate_upcoming(self, weeks=12):
        """Genera las salidas de las próximas `weeks` semanas por rotación de 28
        días desde first_departure_date de cada circuito. Idempotente: no duplica
        (circuit_id, date). Devuelve la cantidad creada."""
        Circuit = self.env['cristal.agent.circuit'].sudo()
        today = self._local_today()
        horizon = today + timedelta(weeks=weeks)
        created = 0
        for circuit in Circuit.search([('active', '=', True)]):
            if not circuit.first_departure_date:
                continue
            d = circuit.first_departure_date
            while d < today:
                d += timedelta(days=28)
            while d <= horizon:
                if not self.search_count([('circuit_id', '=', circuit.id), ('date', '=', d)]):
                    self.create({'circuit_id': circuit.id, 'date': d, 'state': 'preventa'})
                    created += 1
                d += timedelta(days=28)
        _logger.info("generate_upcoming: %s salidas creadas (horizonte %s semanas).",
                     created, weeks)
        return created

    @api.model
    def _cron_generate_upcoming(self):
        """Mantiene siempre 12 semanas de salidas generadas."""
        return self.generate_upcoming(weeks=12)

    # ───────────────────────── Envío de plantillas ─────────────────────────
    def _send_template(self, partner, template_name, values_by_index):
        """Manda una plantilla de la ruta. values_by_index = {n: valor} para cada
        {{n}} del cuerpo. Solo se pasan las variables free_text de la plantilla (las
        de campo, como el nombre, las completa Odoo solo). Devuelve (ok, error)."""
        from ..services.tool_registry import ToolRegistry
        Template = self.env['whatsapp.template'].sudo()
        template = Template.search([('template_name', '=', template_name)], limit=1)
        if not template:
            return False, f"No existe la plantilla {template_name}"
        free_vars = template.variable_ids.filtered(
            lambda v: v.field_type == 'free_text' and v.line_type == 'body')
        ordered = sorted(free_vars, key=lambda v: int(''.join(
            c for c in (v.name or '0') if c.isdigit()) or 0))
        variables = []
        for var in ordered:
            n = int(''.join(c for c in (var.name or '0') if c.isdigit()) or 0)
            variables.append(str(values_by_index.get(n, '')))
        tool = ToolRegistry.get('send_whatsapp_template')
        res = tool.execute(env=self.env, run=None, partner_id=partner.id,
                           template_name=template_name, variables=variables)
        if res.get('error'):
            return False, res['error']
        return True, None

    def _circuit_contacts(self):
        """Contactos del circuito a los que se les puede escribir (con celular y
        sin takeover humano activo)."""
        self.ensure_one()
        Memory = self.env['cristal.agent.memory'].sudo()
        partners = self.env['res.partner'].sudo().search([
            ('truck_circuit_id', '=', self.circuit_id.id),
            ('active', '=', True),
            '|', ('mobile', '!=', False), ('phone', '!=', False),
        ])
        out = self.env['res.partner']
        for p in partners:
            mem = Memory.search([('partner_id', '=', p.id)], limit=1)
            if mem and mem.is_takeover_active():
                continue
            out |= p
        return out

    def _send_batch(self, kind):
        """Tanda de hasta 25 contactos del circuito que todavía no recibieron el
        mensaje (aviso de paso o rescate). Se dispara a mano, tanda por tanda."""
        self.ensure_one()
        if kind == 'aviso':
            template_name, done_field = 'ruta_aviso_paso', 'aviso_partner_ids'
        else:
            template_name, done_field = 'ruta_rescate', 'rescate_partner_ids'
            if self.state != 'rescate':
                raise UserError("El rescate solo se manda con la salida en estado Rescate.")
        pending = self._circuit_contacts() - self[done_field]
        batch = pending[:BATCH_SIZE]
        if not batch:
            raise UserError("No quedan contactos pendientes para este envío.")
        cutoff = self.get_cutoff_local()
        sent, errors = self.env['res.partner'], []
        for partner in batch:
            city = partner.city or self.circuit_id.name
            values = {1: partner.name, 2: _ddmm(self.date), 3: city,
                      4: cutoff.strftime('%d/%m')}
            ok, err = self._send_template(partner, template_name, values)
            if ok:
                sent |= partner
            else:
                errors.append(f"{partner.name}: {err}")
        if sent:
            self.write({done_field: [(4, p.id) for p in sent]})
        remaining = len(pending) - len(sent)
        msg = (f"Enviados {len(sent)} de {len(batch)}. Quedan {remaining} pendientes.")
        if errors:
            msg += " Errores: " + "; ".join(errors[:5])
        _logger.info("Ruta %s %s: %s", self.name, kind, msg)
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': "Tanda enviada" if sent else "No se envió nada",
                       'message': msg, 'type': 'success' if sent else 'warning',
                       'sticky': bool(errors)},
        }

    def action_send_aviso_batch(self):
        return self._send_batch('aviso')

    def action_send_rescate_batch(self):
        return self._send_batch('rescate')

    def action_send_rescheduled(self):
        """Avisa la reprogramación a los clientes con pedido en esta salida."""
        self.ensure_one()
        if not self.original_date or self.original_date == self.date:
            raise UserError("Primero cambiá la fecha de la salida (postergala).")
        partners = self.order_ids.filtered(
            lambda o: o.state != 'cancel').mapped('partner_id')
        sent, errors = 0, []
        for partner in partners:
            values = {1: partner.name, 2: partner.city or self.circuit_id.name,
                      3: _ddmm(self.original_date), 4: _ddmm(self.date)}
            ok, err = self._send_template(partner, 'ruta_salida_reprogramada', values)
            if ok:
                sent += 1
            else:
                errors.append(f"{partner.name}: {err}")
        msg = f"Avisados {sent} de {len(partners)}."
        if errors:
            msg += " Errores: " + "; ".join(errors[:5])
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': "Reprogramación", 'message': msg,
                       'type': 'success' if sent else 'warning', 'sticky': bool(errors)},
        }

    # ───────────────────────── Crons (inactivos hasta aprobación Meta) ─────────────────────────
    @api.model
    def _cron_aviso_ready(self):
        """T-7: avisa en el canal interno que el aviso de paso está listo para
        dispararse (NO manda WhatsApp: el envío es manual, en tandas de 25)."""
        target = self._local_today() + timedelta(days=7)
        deps = self.search([('date', '=', target), ('state', 'in', ('preventa', 'rescate'))])
        if not deps:
            return
        config = self.env['cristal.agent.config'].sudo().get_active()
        channel = config.internal_channel_id if config else False
        for dep in deps:
            n = len(dep._circuit_contacts() - dep.aviso_partner_ids)
            body = (f"🚚 Aviso de paso listo: {dep.name}. {n} contactos del circuito. "
                    f"Dispará las tandas de 25 desde la salida (Ruta del camión → Salidas).")
            if channel:
                channel.sudo().message_post(body=body, message_type='comment',
                                            subtype_xmlid='mail.mt_comment')

    @api.model
    def _cron_confirmations(self):
        """T-1 (miércoles): confirma la entrega a las órdenes confirmadas de la salida."""
        target = self._local_today() + timedelta(days=1)
        for dep in self.search([('date', '=', target), ('state', '!=', 'realizada')]):
            for order in dep.order_ids.filtered(lambda o: o.state in ('sale', 'done')):
                partner = order.partner_id
                values = {1: partner.name, 2: _ddmm(dep.date),
                          3: partner.city or dep.circuit_id.name,
                          4: _fmt_money(order.amount_total),
                          5: order.payment_term_id.name or DEFAULT_PAYMENT_TEXT}
                ok, err = dep._send_template(partner, 'ruta_confirmacion_entrega', values)
                if not ok:
                    _logger.warning("Confirmación de ruta %s a %s falló: %s",
                                    dep.name, partner.name, err)

    @api.model
    def _cron_next_pass(self):
        """T+1 (viernes): a quienes recibieron, agenda la próxima pasada."""
        target = self._local_today() - timedelta(days=1)
        for dep in self.search([('date', '=', target)]):
            nxt = dep.circuit_id.get_next_departure()
            if not nxt:
                continue
            cutoff = nxt.get_cutoff_local()
            partners = dep.order_ids.filtered(
                lambda o: o.state in ('sale', 'done')).mapped('partner_id')
            for partner in partners:
                values = {1: partner.name, 2: partner.city or dep.circuit_id.name,
                          3: _ddmm(nxt.date), 4: cutoff.strftime('%d/%m')}
                ok, err = dep._send_template(partner, 'ruta_proxima_pasada', values)
                if not ok:
                    _logger.warning("Próxima pasada %s a %s falló: %s",
                                    dep.name, partner.name, err)
