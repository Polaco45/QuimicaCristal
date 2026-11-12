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
    # v1.67 — Cuándo se le pidió a Joaco por WhatsApp que confirme este pedido.
    cristal_owner_confirm_at = fields.Datetime(
        string="Confirmación pedida a Joaco (WhatsApp)", copy=False, readonly=True)

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
                                   'cristal_confirm_notice_note': 'Lo confirmó Claudio'})
            else:
                self.sudo().cristal_confirm_notice = 'pending'

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

    def _cristal_confirm_notice_text(self):
        """Texto del aviso, sin saludo (la plantilla de ventana cerrada ya lo trae)."""
        self.ensure_one()
        from ..services.helpers import fmt_day, to_ar
        parts = [f"Tu pedido {self.name} quedó confirmado ✅."]
        dep = self.route_departure_id
        if dep and dep.date:
            circ = f" (circuito {dep.circuit_id.name})" if dep.circuit_id else ""
            parts.append(f"Va en el camión del {fmt_day(dep.date)}{circ}.")
        elif self.cristal_delivery_mode == 'retiro':
            parts.append("Te avisamos cuando esté listo para retirar.")
        elif self.commitment_date:
            parts.append(f"Te lo llevamos el {fmt_day(to_ar(self.env, self.commitment_date).date())}.")
        else:
            parts.append("Te avisamos el día de la entrega.")
        total = f"{self.amount_total:,.0f}".replace(',', '.')
        parts.append(f"Total: ${total}.")
        parts.append("Cualquier cosa escribinos por acá.")
        return " ".join(parts)

    def _cristal_send_confirm_notice(self):
        """Manda el aviso por el chat de WhatsApp del cliente (con la ventana cerrada
        sale por la plantilla genérica). Devuelve (estado, detalle)."""
        self.ensure_one()
        if self.state not in ('sale', 'done'):
            return 'skipped', 'El pedido ya no está confirmado'
        if not self._cristal_is_mayorista():
            return 'skipped', 'No es mayorista'
        partner = self.partner_id.sudo()
        channel = self.env['discuss.channel'].sudo().search([
            ('channel_type', '=', 'whatsapp'), ('channel_partner_ids', 'in', partner.ids)],
            order='write_date desc', limit=1)
        if not channel or not channel.wa_account_id or not channel.whatsapp_number:
            return 'skipped', 'Sin chat de WhatsApp'
        # Si alguien del equipo ya le escribió desde la confirmación, no se repite.
        config = self.env['cristal.agent.config'].sudo().get_active()
        bot_pid = config.bot_partner_id.id if config and config.bot_partner_id else 2
        since = (self.date_order or fields.Datetime.now()) - timedelta(hours=1)
        human = self.env['mail.message'].sudo().search([
            ('model', '=', 'discuss.channel'), ('res_id', '=', channel.id),
            ('date', '>=', since), ('author_id', 'not in', [bot_pid, 2]),
            ('author_id.user_ids.share', '=', False)], limit=1)   # usuarios internos
        if human:
            return 'skipped', f"Ya le escribió {human.author_id.name}"
        from ..services.tool_registry import ToolRegistry
        tool = ToolRegistry.get('send_whatsapp')
        if not tool:
            return 'pending', 'Herramienta send_whatsapp no disponible'
        env = self.env(context=dict(self.env.context, from_cristal_agent=True))
        res = tool.execute(env=env, run=None, channel_id=channel.id,
                           body=self._cristal_confirm_notice_text(),
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
            order.write({'cristal_confirm_notice': state, 'cristal_confirm_notice_note': note})
            if state == 'sent':
                order.message_post(body=f"📲 Aviso de pedido confirmado: {note.lower()}.",
                                   subtype_xmlid='mail.mt_note')
            self.env.cr.commit()
        return True

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
