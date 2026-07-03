# -*- coding: utf-8 -*-
"""
Tool: add_free_samples

Promo "3 muestras gratis": si la compra supera $60.000, se agregan 3 muestras
GRATIS (botellitas ~500ml) a la cotización. Se eligen muestras de productos que
el cliente NO está comprando (para que pruebe algo nuevo); si ya tiene todo
cubierto, 3 al azar de las que haya en stock. Acumulable con el 20% OFF.

Sirve como UPSELL: si el total está por debajo de $60.000, la tool NO agrega nada
y devuelve cuánto falta para llegar y ganarse las muestras.

Las muestras se identifican por la palabra "Muestra" en el nombre del producto y
deben tener stock. Cada muestra se relaciona con su producto a granel para
comunicarle al cliente el precio por litro (para su próxima compra).
"""
import logging
import random
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class AddFreeSamples(AgentTool):
    name = "add_free_samples"

    SAMPLES_THRESHOLD = 60000.0   # compra mínima para ganarse las muestras
    SAMPLES_COUNT = 3             # cantidad de muestras

    description = (
        "Promo de muestras gratis. Llamala DESPUÉS de armar la cotización, cuando "
        "el total supere $60.000: agrega 3 muestras GRATIS de productos que el "
        "cliente NO está comprando (si ya tiene todo, 3 al azar de las que hay en "
        "stock) y te devuelve, por cada muestra, el precio por litro del granel "
        "para que se lo comuniques ('te llevás esta gratis; si te gusta, el litro "
        "sale $X para tu próxima compra'). Si el total está por debajo de $60.000, "
        "NO agrega nada y te dice cuánto falta para llegar (usalo como upsell)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del partner cliente."},
        },
        "required": ["partner_id"],
    }

    # ── Helpers ──
    def _find_granel(self, env, sample_name):
        """Resuelve el product.product a granel asociado a una muestra (por nombre)."""
        Product = env['product.product'].sudo()
        base = (sample_name or '').lower().replace('muestra', '').strip()
        words = [w for w in base.split() if len(w) > 2]
        # Intentos: todas las palabras + granel, luego menos palabras.
        for cut in range(len(words), 0, -1):
            domain = [('sale_ok', '=', True), ('name', 'ilike', 'granel')]
            for w in words[:cut]:
                domain.append(('name', 'ilike', w))
            g = Product.search(domain, limit=1)
            if g:
                return g
        return env['product.product']

    def _price_per_l(self, env, product, pricelist):
        if not product or not pricelist:
            return None
        try:
            price = pricelist._get_product_price(product, 1.0)
            return round(price, 2) if isinstance(price, (int, float)) else None
        except Exception:
            return None

    def _execute(self, env, run=None, partner_id=None, **kwargs):
        if not partner_id:
            return {"error": "partner_id es obligatorio"}
        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        # Cotización draft del cliente
        Lead = env['crm.lead'].sudo()
        opp = Lead.search([
            ('partner_id', '=', partner.id),
            ('type', '=', 'opportunity'),
            ('active', '=', True),
            ('stage_id', 'not in', [4, 13]),
        ], limit=1, order='create_date desc')
        order = None
        if opp:
            order = env['sale.order'].sudo().search([
                ('opportunity_id', '=', opp.id), ('state', '=', 'draft'),
            ], order='create_date desc', limit=1)
        if not order:
            return {"error": f"{partner.name} no tiene una cotización abierta (draft)."}

        total = order.amount_total

        # ¿Llega al umbral?
        if total < self.SAMPLES_THRESHOLD:
            falta = self.SAMPLES_THRESHOLD - total
            return {
                "ok": False,
                "below_threshold": True,
                "total_amount": total,
                "threshold": self.SAMPLES_THRESHOLD,
                "falta": falta,
                "message_for_bot": (
                    f"El total va ${total:,.0f}. Faltan ${falta:,.0f} para llegar a "
                    f"${self.SAMPLES_THRESHOLD:,.0f} y ganarse 3 MUESTRAS GRATIS de "
                    f"productos que todavía no lleva. Ofrecéselo como gancho para que "
                    f"sume: 'si llegás a $60.000 te mando 3 botellitas gratis para probar'."),
            }

        # ¿Ya se agregaron muestras a esta cotización? (evitar duplicar)
        already = order.order_line.filtered(
            lambda l: l.product_id.name and 'muestra' in l.product_id.name.lower())
        if already:
            samples_prev = [l.product_id.name.strip() for l in already]
            return {
                "ok": True,
                "already_added": True,
                "order_id": order.id,
                "samples": samples_prev,
                "message_for_bot": (
                    f"La cotización ya tiene las muestras gratis: "
                    f"{', '.join(samples_prev)}. No agregues más."),
            }

        # Muestras en stock
        Product = env['product.product'].sudo()
        samples = Product.search([('name', 'ilike', 'muestra'), ('sale_ok', '=', True)])
        in_stock = [s for s in samples if (s.qty_available or 0.0) > 0]
        if not in_stock:
            return {
                "ok": False,
                "no_stock": True,
                "message_for_bot": (
                    "No hay muestras en stock ahora mismo. No prometas muestras; "
                    "seguí con la venta normal."),
            }

        # Productos que YA compra (para NO regalarle muestra de algo que ya lleva)
        ordered_pids = set(order.order_line.mapped('product_id').ids)
        pricelist = env['product.pricelist'].sudo().search(
            [('name', '=', 'Lista Mayorista')], limit=1)

        # Preferir muestras cuyo granel NO está en el pedido; después el resto.
        priority, fallback = [], []
        for s in in_stock:
            granel = self._find_granel(env, s.name)
            entry = (s, granel)
            if granel and granel.id in ordered_pids:
                fallback.append(entry)
            else:
                priority.append(entry)

        random.shuffle(priority)
        random.shuffle(fallback)
        chosen = (priority + fallback)[:self.SAMPLES_COUNT]

        # Agregar como líneas GRATIS ($0)
        chosen_info = []
        for s, granel in chosen:
            try:
                order.write({'order_line': [(0, 0, {
                    'product_id': s.id,
                    'product_uom_qty': 1,
                    'price_unit': 0.0,
                    'discount': 0.0,
                    'name': f"{s.name.strip()} — MUESTRA GRATIS (promo +$60.000)",
                })]})
            except Exception as e:
                _logger.warning("No se pudo agregar muestra %s: %s", s.id, e)
                continue
            precio_l = self._price_per_l(env, granel, pricelist)
            chosen_info.append({
                'muestra': s.name.strip(),
                'granel': granel.display_name if granel else None,
                'precio_por_litro': precio_l,
            })

        if not chosen_info:
            return {"error": "No pude agregar las muestras a la cotización."}

        # Registrar en la opp y agendar chequeo a +2 días (post-entrega)
        try:
            opp.message_post(body=(
                "🎁 Muestras gratis agregadas (promo +$60.000): %s" % (
                    ', '.join(c['muestra'] for c in chosen_info))))
        except Exception:
            pass
        self._schedule_followup(env, opp, partner, chosen_info)

        # Texto sugerido para el bot
        lineas = []
        for c in chosen_info:
            if c['precio_por_litro']:
                lineas.append(f"• {c['muestra']} (si te gusta, el litro sale "
                              f"${c['precio_por_litro']:,.0f})")
            else:
                lineas.append(f"• {c['muestra']}")

        return {
            "ok": True,
            "order_id": order.id,
            "order_total": total,
            "samples": chosen_info,
            "message_for_bot": (
                "Agregá al mensaje: 'Como tu compra supera los $60.000, te sumo 3 "
                "MUESTRAS GRATIS para que pruebes (poco menos de 500ml c/u): "
                + " ; ".join(lineas) +
                ". Tenelas en cuenta para tu próxima compra 😉'. En 2 días le "
                "escribís para saber cómo va la venta y qué le parecieron."),
        }

    def _schedule_followup(self, env, opp, partner, chosen_info):
        """Agenda un chequeo del bot a +2 días: cómo va la venta + muestras."""
        from odoo import fields as odoo_fields
        from datetime import timedelta
        config = env['cristal.agent.config'].sudo().get_active()
        bot_uid = config.bot_user_id.id if config.bot_user_id else 1
        check_date = odoo_fields.Date.today() + timedelta(days=2)
        act_type = env['mail.activity.type'].sudo().search(
            [('name', '=', 'Iniciativa de venta')], limit=1)
        if not act_type:
            act_type = env['mail.activity.type'].sudo().browse(4)
        if not act_type.exists():
            return
        muestras = ', '.join(c['muestra'] for c in chosen_info)
        try:
            env['mail.activity'].sudo().create({
                'res_model': 'crm.lead',
                'res_model_id': env['ir.model']._get_id('crm.lead'),
                'res_id': opp.id,
                'activity_type_id': act_type.id,
                'user_id': bot_uid,
                'date_deadline': check_date,
                'summary': f"Post-venta + muestras: {partner.name}",
                'note': (
                    f"Se enviaron muestras gratis ({muestras}). Escribile con la "
                    f"cadencia normal: cómo va la venta, qué le parecieron las "
                    f"muestras gratis, y que estás a disposición."),
            })
        except Exception as e:
            _logger.warning("No se pudo agendar chequeo de muestras: %s", e)
