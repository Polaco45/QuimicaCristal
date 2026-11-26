# -*- coding: utf-8 -*-
"""
Hook en sale.order.

Cuando una cotización se CONFIRMA (pasa a 'sale'/'done') — la cierre Joaco a mano
o el bot — avanzamos la fase comercial del cliente y cortamos la cadencia de
seguimiento. Objetivo: el bot NUNCA persigue a quien ya compró ni lo trata como
cliente nuevo. El estado del cliente queda siempre correcto (principio de
"operario que revisa antes de consultar").

Bugs reales que esto corrige:
- Silvia: compró, Joaco confirmó a mano, y al otro día el bot le escribía
  "¿vas a querer los productos?" pensando que la venta nunca se gestionó.
- Ariel: 3ra compra y el bot lo trataba como primera (fase nunca avanzaba).
"""
import logging
from datetime import timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Fases desde las que tiene sentido avanzar a "primera compra hecha".
_ADVANCEABLE_PHASES = (
    'not_qualified', 'phase_1_qualifying', 'phase_1_qualified',
    'phase_2_post_sample', 'phase_2_quoted',
)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Ruta del camión (v1.32): salida (miércoles desde v1.35) a la que va esta orden.
    route_departure_id = fields.Many2one(
        'cristal.agent.route.departure', string="Salida de ruta (camión)",
        index=True, copy=False, ondelete='set null',
        help="Salida de la ruta del camión a la que se asignó esta orden.")
    # Bidones (v1.33): el cliente ya respondió cuántos vacíos tiene para el recambio.
    cristal_bidones_answered = fields.Boolean(
        string="Bidones consultados", copy=False,
        help="El cliente ya dijo cuántos bidones vacíos tiene para el recambio.")

    # Envío sin cargo acordado (v1.37): Joaco/el equipo le prometió el envío sin
    # cargo a este cliente. Con esto en True, NINGÚN cálculo agrega la línea de
    # flete de la ruta, aunque el pedido quede por debajo del umbral. Solo lo marca
    # un usuario interno (vendedores); Claudio no puede tocarlo.
    route_free_shipping_granted = fields.Boolean(
        string="Envío sin cargo acordado", copy=False, tracking=True,
        groups='sales_team.group_sale_salesman',
        help="Marcalo si se le prometió el envío sin cargo a este cliente: la "
             "cotización no lleva flete de ruta aunque no llegue al monto de envío "
             "sin cargo. Claudio nunca lo marca.")

    # v1.38 — Cómo recibe el pedido: con retiro en planta no hay compra mínima ni flete.
    cristal_delivery_mode = fields.Selection(
        [('envio', 'Envío'), ('retiro', 'Retira en planta')],
        string="Entrega", copy=False, tracking=True,
        help="Lo carga Claudio al cotizar. Retira en planta = sin compra mínima ni flete.")

    # v1.62 — Aviso de pedido confirmado (conversión, punto 7): el 35 % de los pases a
    # Joaco eran "¿se confirmó mi pedido?". Al confirmar a mano un pedido mayorista, el
    # cron le avisa al cliente por WhatsApp (si lo confirmó Claudio, ya se lo dijo él).
    cristal_confirm_notice = fields.Selection(
        [('pending', 'Pendiente'), ('sent', 'Enviado'), ('skipped', 'No se envió')],
        string="Aviso de confirmación", copy=False, readonly=True)
    cristal_confirm_notice_note = fields.Char(
        string="Detalle del aviso", copy=False, readonly=True)
    # v1.73 — Detalle de pago: forma de pago acordada y último total avisado al cliente
    # (si el pedido cambia después de avisado, se le manda el detalle actualizado).
    cristal_payment = fields.Selection(
        [('efectivo', 'Efectivo (contra entrega o al retirar)'),
         ('transferencia', 'Transferencia anticipada')],
        string="Forma de pago acordada", copy=False, tracking=True)
    cristal_notice_total = fields.Float(
        string="Total avisado al cliente", copy=False, readonly=True)
    # v1.67 — Cuándo se le pidió a Joaco por WhatsApp que confirme este pedido.
    cristal_owner_confirm_at = fields.Datetime(
        string="Confirmación pedida a Joaco (WhatsApp)", copy=False, readonly=True)
    # v1.76 — Cuándo se le pidió el OK al CLIENTE (recordatorio de cotización sin confirmar).
    cristal_ok_reminder_at = fields.Datetime(
        string="OK pedido al cliente (WhatsApp)", copy=False, readonly=True)

    # ───────────────────── Flete de la ruta (v1.37) ─────────────────────
    def _cristal_freight_product(self, config):
        if config and config.route_freight_product_id:
            return config.route_freight_product_id
        return self.env['product.product'].sudo().search(
            [('default_code', '=', 'FLETE-ZONA')], limit=1)

    def _cristal_shipping_base(self, config):
        """Base del umbral de ENVÍO SIN CARGO: subtotal sin IVA de los PRODUCTOS, sin
        la línea de flete ni los bidones nuevos (misma base que el mínimo de la ruta).
        Joaco (15/10/2026): el bidón deja ~15% de margen; si contara, 2 bidones
        ($7.000) le ahorrarían al cliente $9.000 de flete."""
        self.ensure_one()
        excluded = self._cristal_freight_product(config)
        if config and config.bidon_product_id:
            excluded |= config.bidon_product_id
        return sum(self.order_line.filtered(
            lambda l: l.product_id not in excluded).mapped('price_subtotal'))

    def _cristal_apply_route_freight(self, config, free_from):
        """Saca el flete anterior y lo vuelve a poner SOLO si corresponde:
        sin 'envío sin cargo acordado' y con la base por debajo de free_from
        (config.route_free_shipping_from, o el umbral de rescate). Devuelve
        (flete, base)."""
        self.ensure_one()
        freight_product = self._cristal_freight_product(config)
        if freight_product:
            self.order_line.filtered(lambda l: l.product_id == freight_product).unlink()
        base = self._cristal_shipping_base(config)
        freight = 0.0
        if freight_product and not self.sudo().route_free_shipping_granted \
                and base < (free_from or 0.0):
            freight = config.route_freight_amount
            self.write({'order_line': [(0, 0, {
                'product_id': freight_product.id, 'product_uom_qty': 1,
                'price_unit': freight, 'discount': 0.0})]})
            # Última palabra sobre el precio: la Lista Mayorista tiene una regla
            # global de -20% que Odoo podría aplicar al flete.
            self.order_line.filtered(lambda l: l.product_id == freight_product).write(
                {'price_unit': freight, 'discount': 0.0})
        return freight, base

    def write(self, vals):
        # Claudio (contexto from_cristal_agent) nunca marca el envío sin cargo.
        if self.env.context.get('from_cristal_agent') \
                and 'route_free_shipping_granted' in vals:
            vals = dict(vals)
            vals.pop('route_free_shipping_granted')
        res = super().write(vals)
        # Si se acordó el envío sin cargo, se saca el flete de las cotizaciones.
        if vals.get('route_free_shipping_granted'):
            config = self.env['cristal.agent.config'].sudo().get_active()
            for order in self.filtered(lambda o: o.state in ('draft', 'sent')):
                freight = order._cristal_freight_product(config)
                if freight:
                    order.order_line.filtered(lambda l: l.product_id == freight).unlink()
        if vals.get('state') in ('sale', 'done'):
            for order in self:
                try:
                    order._cristal_on_confirm()
                except Exception as e:
                    _logger.warning("cristal_on_confirm falló para %s: %s", order.id, e)
        # v1.73 — el detalle de pago de la nota sigue al pedido: si cambian las líneas, la
        # forma de pago o la entrega, se rehace (nunca queda un total viejo en la cotización).
        if not self.env.context.get('cristal_no_note_refresh') and (
                {'order_line', 'cristal_payment', 'cristal_delivery_mode', 'state'} & set(vals)):
            try:
                with self.env.cr.savepoint():
                    self._cristal_refresh_payment_note()
            except Exception as e:  # noqa: BLE001
                _logger.warning("Detalle de pago en la nota falló: %s", e)
        return res

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            try:
                order._cristal_on_confirm()
            except Exception as e:
                _logger.warning("cristal_on_confirm (action_confirm) falló para %s: %s",
                                order.id, e)
        return res

    def _cristal_on_confirm(self):
        """Avanza la fase del lead agent-managed y corta la cadencia."""
        self.ensure_one()
        opp = self.opportunity_id
        if opp and getattr(opp, 'agent_managed', False) \
                and opp.agent_strategy_phase in _ADVANCEABLE_PHASES:
            try:
                opp.write({'agent_strategy_phase': 'phase_3_first_purchase_done'})
                _logger.info(
                    "✅ Venta confirmada: %s → fase 'primera compra hecha'.",
                    opp.partner_id.name if opp.partner_id else opp.name)
            except Exception as e:
                _logger.warning("No pude avanzar la fase del lead %s: %s", opp.id, e)
        # Cortar la cadencia de seguimiento del cliente (no perseguir a quien compró).
        if self.partner_id:
            mem = self.env['cristal.agent.memory'].sudo().search(
                [('partner_id', '=', self.partner_id.id)], limit=1)
            if mem:
                mem.last_cadence_step_executed = 999
        # v1.56 — Referidos: el crédito usado se consume; la primera compra de un referido
        # le da su crédito a quien lo recomendó (y Claudio le avisa).
        try:
            self._cristal_referral_on_confirm()
        except Exception as e:  # noqa: BLE001
            _logger.warning("referidos al confirmar %s: %s", self.name, e)
        # v1.70 — Retención: el pedido consume el cupón y el envío sin cargo vigentes; la
        # PRIMERA compra mayorista deja un cupón de 2ª compra (10 %, tope $8.000, 21 días).
        try:
            self._cristal_retention_on_confirm()
        except Exception as e:  # noqa: BLE001
            _logger.warning("retención al confirmar %s: %s", self.name, e)

    def _cristal_retention_on_confirm(self):
        partner = self.partner_id.sudo().commercial_partner_id
        if not partner or 'agent_coupon_pct' not in partner._fields:
            return
        from .agent_lifecycle import COUPON_2ND
        if self.name and self.name in (partner.agent_coupon_note or ''):
            return                      # ya se procesó esta confirmación
        others = self.env['sale.order'].sudo().search_count([
            ('partner_id', 'child_of', partner.id), ('state', 'in', ('sale', 'done')),
            ('id', '!=', self.id)])
        pos = self.env['pos.order'].sudo().search_count([
            ('partner_id', 'child_of', partner.id),
            ('state', 'in', ('paid', 'done', 'invoiced'))]) if 'pos.order' in self.env else 0
        vals = {}
        if partner.agent_coupon_pct:
            vals.update(agent_coupon_pct=0.0, agent_coupon_cap=0.0,
                        agent_coupon_expires=False, agent_coupon_note=False)
        if partner.agent_free_shipping_until:
            vals['agent_free_shipping_until'] = False
        if vals:
            partner.write(vals)
        if not others and not pos and self._cristal_is_mayorista():
            partner.agent_grant_coupon(COUPON_2ND[0], COUPON_2ND[1], COUPON_2ND[2],
                                       f"segunda compra (por su primer pedido {self.name})")
        # v1.62 — Aviso de confirmación: solo si lo confirmó una persona (Claudio ya
        # le avisa al cliente cuando confirma él).
        if not self.cristal_confirm_notice:
            if self.env.context.get('from_cristal_agent'):
                self.sudo().write({'cristal_confirm_notice': 'skipped',
                                   'cristal_confirm_notice_note': 'Lo confirmó Claudio',
                                   'cristal_notice_total': self.amount_total})
            else:
                self.sudo().cristal_confirm_notice = 'pending'
        # v1.73 — al confirmar, el detalle de pago queda en la nota del pedido (PDF) y en
        # el historial, para quien arma y entrega.
        if self._cristal_is_mayorista():
            self.with_context(cristal_payment_note=True)._cristal_refresh_payment_note()
            from markupsafe import Markup, escape
            self.sudo().message_post(
                body=Markup("💵 <b>Detalle de pago al confirmar</b><br/>") + Markup('<br/>').join(
                    escape(x) for x in self._cristal_payment_detail()),
                subtype_xmlid='mail.mt_note')

    # ───────────── v1.62 — Aviso de pedido confirmado por WhatsApp ─────────────
    def _cristal_is_mayorista(self):
        partner = self.partner_id.sudo()
        commercial = partner.commercial_partner_id
        tags = (partner.category_id | commercial.category_id).mapped('name')
        if 'Mayorista' in tags:
            return True
        return bool(self.env['cristal.agent.memory'].sudo().search_count([
            ('partner_id', 'in', (partner | commercial).ids),
            ('client_type', '=', 'mayorista')]))

    # ───────────── v1.73 — Detalle de pago (qué abona el cliente) ─────────────
    # Joaco (17/11/2026): "tengo muchos problemas a la hora de entregar los pedidos con los
    # montos que da Claudio. Una vez que confirme un pedido tiene que dar el detalle de
    # cuánto deberá abonar el cliente, detallando en la cotización también". Un solo
    # armado, siempre desde el pedido real: mensaje de confirmación, nota de la cotización
    # y nota interna para quien entrega.
    def _cristal_payment_detail(self):
        """Lista de renglones con lo que abona el cliente, calculada del pedido real."""
        self.ensure_one()
        order = self.sudo()
        config = self.env['cristal.agent.config'].sudo().get_active()
        money = lambda v: '${:,.0f}'.format(v or 0).replace(',', '.')  # noqa: E731
        bidon = config.bidon_product_id if config and config.bidon_product_id else \
            self.env['product.product']
        freight = order._cristal_freight_product(config) or self.env['product.product']
        tax_included = abs(order.amount_tax) < 0.5
        amount = (lambda l: l.price_subtotal) if tax_included else (lambda l: l.price_total)
        out, products, bidones, shipping, gross = [], 0.0, 0.0, 0.0, 0.0
        has_shipping = False
        for l in order.order_line:
            if l.display_type:
                continue
            if l.product_id and l.product_id == bidon:
                bidones += amount(l)
                nb = int(l.product_uom_qty)
                out.append(f"• {nb} bidón(es) nuevo(s) de 20 L — {money(amount(l))}")
                continue
            if getattr(l, 'is_delivery', False) or (l.product_id and l.product_id == freight):
                has_shipping = True
                shipping += amount(l)
                continue
            if getattr(l, 'combo_item_id', False) and not amount(l):
                continue
            products += amount(l)
            gross += l.price_unit * l.product_uom_qty
            name = (l.product_id.display_name or l.name or '').split('\n')[0]
            if name.startswith('[') and '] ' in name:      # sin el código interno [PQ0114]
                name = name.split('] ', 1)[1]
            out.append(f"• {l.product_uom_qty:g} {name} — {money(amount(l))}")
        if has_shipping:
            out.append(f"• Envío — {money(shipping) if shipping else 'sin cargo'}")
        elif order.cristal_delivery_mode == 'retiro':
            out.append("• Retira en la planta (sin envío)")
        net_gross = sum(l.price_subtotal for l in order.order_line
                        if not l.display_type and l.discount)
        gross_disc = sum(l.price_unit * l.product_uom_qty for l in order.order_line
                         if not l.display_type and l.discount)
        saved = gross_disc - net_gross
        if saved > 1:
            out.append(f"Descuento ya aplicado en esos precios: {money(saved)}")
        try:
            from ..services.tool_registry import ToolRegistry
            tool = ToolRegistry.get('create_sale_order')
            info = tool._bidones_info(self.env, config, order) if tool else None
            if info and not info['nuevos']:
                out.append(info['summary'])
            elif info and info['needed'] > info['nuevos']:
                rec = info['needed'] - info['nuevos']
                out.append(f"Envases: además {rec} bidón(es) de recambio, que se canjean por "
                           f"vacíos con tapa (sin cargo).")
        except Exception as e:  # noqa: BLE001
            _logger.warning("Detalle de pago %s: bidones no disponibles: %s", order.name, e)
        if not tax_included:
            out.append("(precios con IVA incluido)")
        out.append(f"TOTAL A PAGAR: {money(order.amount_total)}")
        pay = dict(self._fields['cristal_payment'].selection).get(order.cristal_payment)
        if pay:
            out.append(f"Forma de pago: {pay}")
        return out

    _PAYMENT_NOTE_RE = r'<p>\s*<(?:strong|b)>Detalle de pago.*?</p>'

    def _cristal_refresh_payment_note(self):
        """Deja en la nota de la cotización (sale en el PDF) el detalle de pago vigente.
        Solo pedidos mayoristas de Claudio o que ya lo tenían; nunca pisa el resto de la nota."""
        import re
        from markupsafe import Markup, escape
        for order in self.sudo():
            if order.state == 'cancel' or not order.order_line:
                continue
            current = str(order.note or '')
            had = bool(re.search(self._PAYMENT_NOTE_RE, current, re.S))
            if not had and not (self.env.context.get('from_cristal_agent')
                                or self.env.context.get('cristal_payment_note')):
                continue
            body = Markup('<br/>').join(escape(x) for x in order._cristal_payment_detail())
            block = Markup('<p><strong>Detalle de pago</strong><br/>') + body + Markup('</p>')
            rest = re.sub(self._PAYMENT_NOTE_RE, '', current, flags=re.S).strip()
            new = (Markup(rest) if rest and rest != '<p><br></p>' else Markup('')) + block
            if str(new) != current:
                super(SaleOrder, order.with_context(cristal_no_note_refresh=True)).write(
                    {'note': new})

    def _prepare_invoice(self):
        """El detalle de pago es de la cotización: no pasa a la factura."""
        import re
        vals = super()._prepare_invoice()
        if vals.get('narration'):
            vals['narration'] = re.sub(self._PAYMENT_NOTE_RE, '', str(vals['narration']),
                                       flags=re.S) or False
        return vals

    def _cristal_confirm_notice_text(self, updated=False):
        """Texto del aviso, sin saludo (la plantilla de ventana cerrada ya lo trae)."""
        self.ensure_one()
        from ..services.helpers import fmt_day, to_ar
        if updated:
            return self._cristal_detail_html(
                f"Actualizamos tu pedido {self.name}. Así queda:",
                "Cualquier duda escribinos por acá.")
        parts = [f"Tu pedido {self.name} quedó confirmado ✅."]
        dep = self.route_departure_id
        if dep and dep.date:
            circ = f" (circuito {dep.circuit_id.name})" if dep.circuit_id else ""
            parts.append(f"Va en el camión del {fmt_day(dep.date)}{circ}.")
        elif self.cristal_delivery_mode == 'retiro':
            parts.append("Lo preparamos en el día: te confirmamos por acá la hora en que queda listo para retirar.")
        elif self.commitment_date:
            parts.append(f"Te lo llevamos el {fmt_day(to_ar(self.env, self.commitment_date).date())}.")
        else:
            parts.append("Te avisamos el día de la entrega.")
        return self._cristal_detail_html(" ".join(parts) + " Esto es lo que abonás:",
                                         "Cualquier cosa escribinos por acá.")

    def _cristal_detail_html(self, head, tail):
        """Mensaje con el detalle de pago, un renglón por línea. Si es muy largo para la
        plantilla de ventana cerrada (una sola variable de ~900 caracteres), los productos
        se resumen en un renglón: el total y los envases no se cortan nunca."""
        import html as _html
        lines = self._cristal_payment_detail()
        if sum(len(x) + 1 for x in lines) + len(head) + len(tail) > 820:
            prods = [x for x in lines if x.startswith('• ')]
            rest = [x for x in lines if not x.startswith('• ')]
            lines = [f"• {len(prods)} renglones (el detalle completo está en la cotización)"] + rest
        return "<br>".join(_html.escape(x) for x in [head] + lines + [tail])

    def _cristal_send_confirm_notice(self, updated=False):
        """Manda el aviso por el chat de WhatsApp del cliente (con la ventana cerrada
        sale por la plantilla genérica). Devuelve (estado, detalle)."""
        self.ensure_one()
        if self.state not in ('sale', 'done'):
            return 'skipped', 'El pedido ya no está confirmado'
        if not self._cristal_is_mayorista():
            return 'skipped', 'No es mayorista'
        partner = self.partner_id.sudo()
        from ..services.helpers import customer_wa_channel
        channel = customer_wa_channel(self.env, partner)
        if not channel or not channel.wa_account_id or not channel.whatsapp_number:
            return 'skipped', 'Sin chat de WhatsApp'
        # v1.73 — antes no se mandaba si alguien del equipo ya le había escrito; ahora el
        # detalle de lo que abona sale SIEMPRE (Joaco 17/11/2026: los montos tienen que
        # quedar claros antes de la entrega).
        from ..services.tool_registry import ToolRegistry
        tool = ToolRegistry.get('send_whatsapp')
        if not tool:
            return 'pending', 'Herramienta send_whatsapp no disponible'
        env = self.env(context=dict(self.env.context, from_cristal_agent=True))
        res = tool.execute(env=env, run=None, channel_id=channel.id,
                           body=self._cristal_confirm_notice_text(updated=updated),
                           wa_account_id=channel.wa_account_id.id,
                           mobile_number=channel.whatsapp_number) or {}
        if res.get('ok'):
            how = 'por plantilla' if res.get('window_closed') else 'en el chat'
            return 'sent', f"Enviado {how}"
        if res.get('error') == 'TEMPLATE_PENDING':
            return 'pending', 'Espera respuesta a una plantilla anterior'
        return 'skipped', str(res.get('error') or res.get('message') or 'No salió')[:200]

    @api.model
    def cron_confirm_notices(self, limit=30):
        """Cada 10 minutos, en horario de contacto: avisa los pedidos confirmados a mano
        hace más de 5 minutos según date_order (margen por si se confirmó por error). Los que siguen
        pendientes después de 3 días se dan por vencidos."""
        config = self.env['cristal.agent.config'].sudo().get_active()
        if not config or not config.order_confirm_notice:
            return True
        from ..services.helpers import within_contact_hours
        now = fields.Datetime.now()
        stale = self.sudo().search([('cristal_confirm_notice', '=', 'pending'),
                                    ('date_order', '<', now - timedelta(days=3))])
        stale.write({'cristal_confirm_notice': 'skipped',
                     'cristal_confirm_notice_note': 'Vencido (más de 3 días)'})
        if not within_contact_hours(self.env):
            return True
        orders = self.sudo().search([('cristal_confirm_notice', '=', 'pending'),
                                     ('date_order', '<', now - timedelta(minutes=5))],
                                    order='id', limit=limit)
        for order in orders:
            try:
                with self.env.cr.savepoint():
                    state, note = order._cristal_send_confirm_notice()
            except Exception as e:  # noqa: BLE001
                _logger.warning("Aviso de confirmación de %s falló: %s", order.name, e)
                state, note = 'skipped', f"Error: {e}"[:200]
            vals = {'cristal_confirm_notice': state, 'cristal_confirm_notice_note': note}
            if state == 'sent':
                vals['cristal_notice_total'] = order.amount_total
            order.write(vals)
            if state == 'sent':
                order.message_post(body=f"📲 Aviso de pedido confirmado: {note.lower()}.",
                                   subtype_xmlid='mail.mt_note')
            self.env.cr.commit()
        # v1.73 — el pedido cambió DESPUÉS de avisarle el total (alguien agregó o sacó
        # productos, bidones o envío) y todavía no se entregó: se le manda el detalle
        # actualizado, para que el monto que tiene el cliente sea el que se le va a cobrar.
        changed = self.sudo().search([
            ('state', '=', 'sale'), ('cristal_notice_total', '>', 0),
            ('date_order', '>=', now - timedelta(days=10)),
            ('write_date', '<', now - timedelta(minutes=10))], order='id', limit=limit)
        for order in changed:
            if abs(order.amount_total - order.cristal_notice_total) < 1:
                continue
            if order.picking_ids and all(p.state in ('done', 'cancel') for p in order.picking_ids):
                order.cristal_notice_total = order.amount_total    # ya entregado: no se avisa
                self.env.cr.commit()
                continue
            old = order.cristal_notice_total
            try:
                with self.env.cr.savepoint():
                    state, note = order._cristal_send_confirm_notice(updated=True)
            except Exception as e:  # noqa: BLE001
                _logger.warning("Aviso de cambio de %s falló: %s", order.name, e)
                state, note = 'skipped', f"Error: {e}"[:200]
            if state == 'pending':
                continue                      # espera una plantilla anterior: se reintenta
            order.cristal_notice_total = order.amount_total
            order.message_post(
                body=(f"📲 El total cambió de ${old:,.0f} a ${order.amount_total:,.0f}: "
                      .replace(',', '.')
                      + ("se le mandó al cliente el detalle actualizado." if state == 'sent'
                         else f"NO se le pudo avisar al cliente ({note}). Avisarle antes de entregar.")),
                subtype_xmlid='mail.mt_note')
            self.env.cr.commit()
        return True

    # ───────────── v1.76 — Recordatorio de OK al cliente (Joaco ya no confirma) ─────────────
    def _cristal_ok_missing(self):
        """Qué le falta a esta cotización para que Claudio la confirme, dicho para el
        CLIENTE (lista de frases). Sale de la lista de control de confirm_order."""
        self.ensure_one()
        import re
        from ..services.owner_confirm import confirm_blockers
        out = []
        for p in confirm_blockers(self.env, self):
            if p.startswith('falta la dirección'):
                out.append("la dirección exacta de entrega (o si lo retirás en el local)")
            elif p.startswith('falta confirmar los bidones'):
                out.append("cuántos bidones vacíos de 20 L con tapa tenés para el recambio")
            elif p.startswith('envío fuera de'):
                out.append("si lo retirás en nuestro local o lo mandás a buscar con un "
                           "comisionista (a tu localidad no llega nuestro reparto)")
            elif p.startswith('no hay stock suficiente de'):
                m = re.match(r'no hay stock suficiente de (.+?)(?: \(pide|$)', p)
                name = re.sub(r'^\[[^\]]+\]\s*', '', m.group(1)) if m else 'un producto'
                out.append(f"si lo confirmamos con lo que tenemos hoy de {name} o preferís "
                           f"esperar la reposición")
            elif p.startswith('tiene facturas vencidas'):
                out.append("regularizar el saldo pendiente de tu cuenta (te paso el detalle "
                           "si lo necesitás)")
            elif p.startswith('la salida del camión'):
                out.append("si lo retirás en el local o lo dejamos para la próxima salida "
                           "del camión")
        if not self.cristal_payment:
            out.append("si pagás en efectivo o por transferencia")
        return out

    def _cristal_ok_reminder_text(self):
        """Texto del recordatorio: total, cómo se entrega y qué falta para confirmar."""
        self.ensure_one()
        from ..services.helpers import fmt_day
        total = f"${self.amount_total:,.0f}".replace(',', '.')
        dep = self.route_departure_id
        if self.cristal_delivery_mode == 'retiro':
            entrega = "Lo retirás en nuestro local (San Martín 2350, Río Cuarto)."
        elif dep and dep.date and dep.state in ('preventa', 'rescate') \
                and not dep.circuit_id.paused:
            entrega = f"Va en el camión del {fmt_day(dep.date)}."
        elif self.partner_id.agent_zone in ('rio_cuarto', 'las_higueras'):
            entrega = "Te lo llevamos por la mañana; te avisamos el día."
        else:
            entrega = ""
        missing = self._cristal_ok_missing()
        ask = ("Para dejarlo confirmado necesito que me digas: " + "; ".join(missing) + "."
               if missing else "Con tu OK lo dejo confirmado.")
        return (f"Te escribo por tu cotización {self.name}: el total es {total}. "
                + (entrega + " " if entrega else "")
                + "¿La confirmamos? " + ask)

    def cristal_send_ok_reminder(self):
        """Le pide el OK al cliente por WhatsApp (una vez por cotización). Devuelve
        {nombre: resultado}. Lo usa el cron y se puede disparar a mano."""
        from ..services.tool_registry import ToolRegistry
        tool = ToolRegistry.get('send_whatsapp')
        out = {}
        for order in self.sudo():
            if order.state not in ('draft', 'sent'):
                out[order.name] = 'no es cotización'
                continue
            if order.cristal_ok_reminder_at:
                out[order.name] = 'ya se le pidió'
                continue
            partner = order.partner_id
            from ..services.helpers import customer_wa_channel
            ch = customer_wa_channel(self.env, partner)
            if not tool or not ch or not ch.wa_account_id or not ch.whatsapp_number:
                out[order.name] = 'sin chat de WhatsApp'
                continue
            text = order._cristal_ok_reminder_text()
            env2 = self.env(context=dict(self.env.context, from_cristal_agent=True,
                                         wa_transactional=True))
            try:
                res = tool.execute(env=env2, run=None, channel_id=ch.id, body=text,
                                   wa_account_id=ch.wa_account_id.id,
                                   mobile_number=ch.whatsapp_number) or {}
            except Exception as e:  # noqa: BLE001
                _logger.warning("Recordatorio de OK de %s falló: %s", order.name, e)
                res = {'error': str(e)[:120]}
            if res.get('ok'):
                order.cristal_ok_reminder_at = fields.Datetime.now()
                order.message_post(body="📲 Se le pidió el OK al cliente por WhatsApp: " + text,
                                   subtype_xmlid='mail.mt_note')
                out[order.name] = 'enviado'
            else:
                out[order.name] = 'no salió: ' + str(res.get('error') or res.get('message') or '')[:120]
        return out

    @api.model
    def cron_requested_unconfirmed(self, limit=5):
        """Cotización mayorista que el cliente PIDIÓ por WhatsApp ("quiero el pedido",
        "confirmo", "dale") y sigue sin confirmar 24 h después.
        v1.76 — Joaco (18/11/2026): "no quiero intervenir más yo en pedidos, que sea
        autónomo". Ya no se le pide a Joaco: si pasa todos los controles se confirma sola;
        si le falta algo, se le pide el OK al CLIENTE con lo que falta (una vez)."""
        import re
        from ..services.helpers import within_contact_hours
        if not within_contact_hours(self.env):
            return 0
        intent = re.compile(
            r'\b(quiero el pedido|lo quiero|confirm[oa]\b|confirmame|dale|mandame(lo)?|'
            r'hacelo|hac[eé] el pedido|s[ií],? (lo )?(quiero|confirmo))', re.IGNORECASE)
        # Pedido explícito (un "dale" suelto no alcanza para confirmar sin preguntar).
        strong = re.compile(
            r'\b(quiero el pedido|lo quiero|confirmo\b|confirmame|confirmalo|'
            r'hac[eé] el pedido|s[ií],? (lo )?(quiero|confirmo))', re.IGNORECASE)
        from ..services.owner_confirm import confirm_blockers
        now = fields.Datetime.now()
        orders = self.sudo().search([
            ('state', 'in', ('draft', 'sent')), ('cristal_ok_reminder_at', '=', False),
            ('pricelist_id.name', '=', 'Lista Mayorista'),
            ('create_date', '<', now - timedelta(hours=24)),
            ('create_date', '>', now - timedelta(days=14))], order='create_date desc')
        sent = 0
        for order in orders:
            if sent >= limit:
                break
            partner = order.partner_id
            from ..services.helpers import customer_wa_channel
            channel = customer_wa_channel(self.env, partner)
            if not channel:
                continue
            msgs = self.env['mail.message'].sudo().search([
                ('model', '=', 'discuss.channel'), ('res_id', '=', channel.id),
                ('author_id', '=', partner.id), ('date', '>', order.create_date),
                ('date', '<', now - timedelta(hours=24))], order='id desc', limit=8)
            text = ' '.join(re.sub(r'<[^>]+>', ' ', m.body or '') for m in msgs)
            if not intent.search(text):
                continue
            # Si el cliente lo pidió con todas las letras, ya dijo cómo paga y el pedido
            # pasa TODOS los controles, se confirma solo (recibe el aviso con el detalle de
            # pago). Si no, se le pide el OK al cliente con lo que falta.
            if strong.search(text) and order.cristal_payment \
                    and not confirm_blockers(self.env, order):
                try:
                    with self.env.cr.savepoint():
                        order.with_context(from_cristal_agent=True).action_confirm()
                        order.message_post(
                            body=("✅ Confirmado automáticamente: el cliente lo pidió por "
                                  "WhatsApp hace más de 24 h y el pedido pasa todos los "
                                  "controles (monto, zona, stock, bidones, sin deuda)."),
                            subtype_xmlid='mail.mt_note')
                    sent += 1
                    self.env.cr.commit()
                    continue
                except Exception:  # noqa: BLE001 — si no se pudo, se le pide el OK
                    _logger.exception("No pude confirmar solo %s", order.name)
            if order.cristal_send_ok_reminder().get(order.name) == 'enviado':
                sent += 1
            self.env.cr.commit()
        return sent

    def _cristal_referral_on_confirm(self):
        partner = self.partner_id.sudo()
        if not partner or 'agent_referral_credit_pct' not in partner._fields:
            return
        config = self.env['cristal.agent.config'].sudo().get_active()
        credit = partner.agent_referral_credit_pct or 0.0
        others = self.env['sale.order'].sudo().search_count([
            ('partner_id', '=', partner.id), ('state', 'in', ('sale', 'done')),
            ('id', '!=', self.id)])
        used = any(abs((l.discount or 0.0) - credit) < 0.01
                   for l in self.order_line.filtered('product_id')) if credit else False
        # El crédito se consume si se usó o si era para el primer pedido y ya pasó
        # (p. ej. el referido usó el 20 % de primera compra, que es mejor).
        if credit and (used or (partner.agent_referred_by_id and not others)):
            partner.write({'agent_referral_credit_pct': 0.0,
                           'agent_referral_credit_note': False})
            partner.append_agent_observation(
                f"🎁 Crédito por referido {'usado' if used else 'vencido (usó otro descuento)'} en {self.name}.")
        referrer = partner.agent_referred_by_id.sudo()
        if not referrer or partner.agent_referral_rewarded:
            return
        if others:
            partner.agent_referral_rewarded = True   # no era su primera compra
            return
        today = fields.Date.today()
        month_start = today.replace(day=1)
        rewarded_this_month = self.env['res.partner'].sudo().search_count([
            ('agent_referred_by_id', '=', referrer.id), ('agent_referral_rewarded', '=', True),
            ('agent_referral_rewarded_date', '>=', month_start)])
        cap = config.referral_max_per_month if config else 3
        partner.write({'agent_referral_rewarded': True, 'agent_referral_rewarded_date': today})
        if cap and rewarded_this_month >= cap:
            referrer.append_agent_observation(
                f"Referido {partner.name} hizo su primera compra ({self.name}), pero ya se "
                f"premiaron {rewarded_this_month} referidos este mes (tope {cap}).")
            return
        pct = float(config.referral_discount if config else 5.0) or 5.0
        referrer.agent_grant_referral_credit(
            pct, f"{partner.name} (recomendado por usted) hizo su primera compra {self.name}")
        if config and config.bot_user_id:
            referrer.activity_schedule(
                'mail.mail_activity_data_todo', date_deadline=fields.Date.today(),
                user_id=config.bot_user_id.id,
                summary=f"[NBA] Premio por referido: {partner.name} compró",
                note=(f"{partner.name}, que vino recomendado por este cliente, hizo su primera "
                      f"compra ({self.name}). Avisale en una línea, cordial: gracias por la "
                      f"recomendación, su próximo pedido lleva {pct:g}% de descuento (se aplica "
                      f"solo al cotizar). Un solo mensaje, sin presionar a que compre ya."))
