# -*- coding: utf-8 -*-
"""
Tool: create_sale_order

Crea/actualiza UNA cotización (sale.order draft) por cliente.

Reglas de negocio (v1.21):
- COTIZACIÓN ÚNICA: si el cliente ya tiene un borrador abierto (colgado de su
  oportunidad), NO se crea otro: se agregan/mergean las líneas en ESE. Nunca
  varios presupuestos para el mismo cliente.
- MÍNIMO A GRANEL: 20 L por producto, SIN excepción. Si piden menos, se rechaza
  esa línea.
- MÍNIMO DE COMPRA: $50.000 (se comunica + upsell). Piso duro: $39.990 — NO se
  puede cotizar/enviar por menos. Entre 39.990 y 50.000 se permite pero se avisa
  para hacer upsell.
- STOCK: los productos de DISTRIBUCIÓN/secos sin stock se marcan (sin_stock) para
  que el bot ofrezca una alternativa / escale. Los de fabricación a granel se
  producen a pedido → siempre disponibles.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class CreateSaleOrder(AgentTool):
    name = "create_sale_order"

    # Reglas de negocio
    GRANEL_MIN_L = 20          # mínimo a granel por producto, SIN excepción
    COMPRA_MIN = 50000.0       # compra mínima oficial (comunicar + upsell)
    COMPRA_PISO = 39990.0      # piso duro: NO cotizar/enviar por menos

    description = (
        "Crea o ACTUALIZA la ÚNICA cotización (sale.order draft) del cliente. "
        "Si el cliente ya tiene un borrador abierto, agrega/mergea las líneas ahí "
        "(NUNCA crees varios presupuestos para el mismo cliente: mandá TODOS los "
        "productos en una sola llamada o se van sumando al mismo borrador). "
        "Pasale partner_id y lines: {product_id|product_name, qty}. "
        "Reglas que la tool valida sola: mínimo 20 L por producto a granel (sin "
        "excepción), y piso de compra $39.990 (no se puede cotizar por menos). "
        "Pasá discount_percent=20 para el 20% OFF de primera compra. "
        "PROMOS CON PRECIO CERRADO (ej: campaña 'Ariel y Skip a $600 el litro'): pasá "
        "price_unit en la línea (el precio por unidad final de la promo) y NO pases "
        "discount_percent — esos precios NO se acumulan con el 20% de primera compra. "
        "Fijate el campo 'upsell' y 'sin_stock' de la respuesta: si vienen, "
        "comunicáselos al cliente (upsell para llegar a $50.000, alternativa si "
        "algo está sin stock)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del partner cliente."},
            "lines": {
                "type": "array",
                "description": "TODAS las líneas de la cotización de una: "
                               "{product_id (int) o product_name (str)} + qty (number).",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer"},
                        "product_name": {"type": "string"},
                        "qty": {"type": "number"},
                        "price_unit": {
                            "type": "number",
                            "description": "(Opcional) Precio por unidad FIJO para esta línea "
                                           "(promos con precio cerrado, ej: $600/litro). Si lo "
                                           "pasás, se usa ese precio y a esa línea NO se le "
                                           "aplica discount_percent (no acumulable).",
                        },
                    },
                },
            },
            "pricelist_name": {"type": "string", "description": "Default: 'Lista Mayorista'."},
            "note": {"type": "string", "description": "(Opcional) Nota interna."},
            "discount_percent": {
                "type": "number",
                "description": "Descuento % que se aplica a las líneas SIN price_unit fijo. "
                               "20 = primera compra. NO lo pases junto con promos de precio "
                               "cerrado (price_unit) — no son acumulables.",
            },
        },
        "required": ["partner_id", "lines"],
    }

    # ───────────────────────── Helpers de negocio ─────────────────────────
    def _es_granel(self, product):
        """True si el producto se vende a granel (por litro)."""
        name = (product.name or '').lower()
        uom = (product.uom_id.name or '').lower() if product.uom_id else ''
        return ('granel' in name) or uom in ('l', 'lt', 'litro', 'litros', 'l.')

    def _disponibilidad(self, product):
        """Stock disponible para productos de DISTRIBUCIÓN/secos.
        Devuelve None si es fabricación a granel o no trackea stock (siempre disp.)."""
        if self._es_granel(product):
            return None  # fabricación a pedido → siempre disponible
        # Solo productos almacenables (goods con stock) trackean disponibilidad.
        # En Odoo 17/18 esto es is_storable (el tipo 'product' ya no existe).
        if not getattr(product, 'is_storable', False):
            return None
        try:
            return product.qty_available or 0.0
        except Exception:
            return None

    def _resolver_producto(self, env, ln):
        """Resuelve el product.product de una línea (id o nombre fuzzy)."""
        Product = env['product.product'].sudo()
        product = None
        if ln.get('product_id'):
            product = Product.browse(int(ln['product_id']))
            if not product.exists():
                product = None
        if not product and ln.get('product_name'):
            name = ln['product_name'].strip()
            words = [w for w in name.split() if len(w) > 1]
            if words:
                domain_words = [('product_tmpl_id.is_mayorista_catalog', '=', True),
                                ('sale_ok', '=', True)]
                for w in words:
                    domain_words.append(('name', 'ilike', w))
                product = Product.search(domain_words, limit=1)
            if not product and words:
                domain_words = [('sale_ok', '=', True)]
                for w in words:
                    domain_words.append(('name', 'ilike', w))
                product = Product.search(domain_words, limit=1)
            # Fallback interpretativo: la palabra más significativa sola, para no
            # fallar por diferencias de wording (ej: "perfume textil" no matchea
            # "Perfume p/ropa" con TODAS las palabras, pero sí con "perfume").
            if not product and words:
                key = max(words, key=len)
                product = Product.search(
                    [('product_tmpl_id.is_mayorista_catalog', '=', True),
                     ('sale_ok', '=', True), ('name', 'ilike', key)], limit=1)
                if not product:
                    product = Product.search(
                        [('sale_ok', '=', True), ('name', 'ilike', key)], limit=1)
            if not product:
                product = Product.search([('name', 'ilike', name), ('sale_ok', '=', True)], limit=1)
        return product

    # ─────────────────────────────── Main ───────────────────────────────
    def _execute(self, env, run=None, partner_id=None, lines=None,
                 pricelist_name='Lista Mayorista', note=None,
                 discount_percent=None, **kwargs):
        if not (partner_id and lines):
            return {"error": "partner_id y lines son obligatorios"}

        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        # ── GUARDRAIL: el 20% es SOLO de PRIMERA compra ──
        # Bug real (caso Ariel, 3ra compra): el bot aplicó el 20% de primera compra
        # a un cliente que YA había comprado. No se puede confiar en que el LLM
        # infiera "primera compra": la tool valida el historial. Si el cliente ya
        # tiene ventas confirmadas y se pasó un descuento tipo primera compra
        # (>=15%), se BLOQUEA y se cotiza a precio de nivel normal.
        prev_purchases = env['sale.order'].sudo().search_count([
            ('partner_id', '=', partner.id),
            ('state', 'in', ['sale', 'done']),
        ])
        first_purchase_blocked = False
        if prev_purchases > 0 and discount_percent and float(discount_percent) >= 15:
            first_purchase_blocked = True
            _logger.info(
                "🚫 20%% de primera compra BLOQUEADO: %s ya tiene %s compra(s) "
                "confirmada(s).", partner.name, prev_purchases)
            discount_percent = None

        Pricelist = env['product.pricelist'].sudo()
        pricelist = Pricelist.search([('name', '=', pricelist_name)], limit=1)
        if not pricelist and pricelist_name != 'Lista Mayorista':
            pricelist = Pricelist.search([('name', '=', 'Lista Mayorista')], limit=1)
        if not pricelist:
            # NUNCA caer a la pricelist del partner: los consumidor final /
            # re-etiquetados tienen L.C 1 y las cotizaciones mayoristas DEBEN ir
            # SIEMPRE con la Lista Mayorista.
            return {"error": "No encontré la 'Lista Mayorista'. Las cotizaciones "
                             "mayoristas DEBEN usar esa lista. Escalá a Joaco."}

        # 1) Resolver líneas + validar mínimo a granel + stock
        resolved = []  # (product, qty, fixed_price)
        fixed_price_pids = set()  # productos con precio de promo cerrado (no 20%)
        problems = []
        sin_stock = []
        for i, ln in enumerate(lines):
            qty = float(ln.get('qty', 0))
            if qty <= 0:
                problems.append(f"Línea {i+1}: qty inválida ({qty})")
                continue
            product = self._resolver_producto(env, ln)
            if not product:
                problems.append(
                    f"Línea {i+1}: no encontré el producto "
                    f"(id={ln.get('product_id')}, name={ln.get('product_name')})")
                continue
            # Mínimo a granel 20 L — SIN excepción
            if self._es_granel(product) and qty < self.GRANEL_MIN_L:
                problems.append(
                    f"'{product.display_name}': el mínimo a granel es "
                    f"{self.GRANEL_MIN_L} L por producto SIN excepción "
                    f"(pediste {qty:g}). Subí a {self.GRANEL_MIN_L} L o más.")
                continue
            # Stock (solo distribución/secos)
            disp = self._disponibilidad(product)
            if disp is not None and disp <= 0:
                sin_stock.append(product.display_name)
            # Precio fijo de promo (opcional): esa línea NO lleva el 20% (no acumulable)
            fp = ln.get('price_unit')
            try:
                fixed_price = float(fp) if fp not in (None, '', 0, 0.0) else None
            except (TypeError, ValueError):
                fixed_price = None
            if fixed_price is not None:
                fixed_price_pids.add(product.id)
            resolved.append((product, qty, fixed_price))

        if not resolved:
            return {
                "error": "No hay líneas válidas para cotizar (revisá mínimos y nombres).",
                "problems": problems,
                "sin_stock": sin_stock or None,
            }

        # 2) Oportunidad + cotización ÚNICA (reusar borrador si existe)
        Lead = env['crm.lead'].sudo()
        opp = Lead.search([
            ('partner_id', '=', partner.id),
            ('type', '=', 'opportunity'),
            ('active', '=', True),
            ('stage_id', 'not in', [4, 13]),
        ], limit=1, order='create_date desc')
        if not opp:
            opp = Lead.create({
                'name': partner.name or 'Cliente mayorista',
                'partner_id': partner.id,
                'type': 'opportunity',
                'agent_managed': True,
            })

        SaleOrder = env['sale.order'].sudo()
        order = SaleOrder.search([
            ('opportunity_id', '=', opp.id),
            ('state', '=', 'draft'),
        ], order='create_date desc', limit=1)

        try:
            if order:
                # Mergear en el borrador existente (una sola cotización)
                for product, qty, fixed_price in resolved:
                    existing = order.order_line.filtered(
                        lambda l: l.product_id.id == product.id)
                    if existing:
                        existing[0].product_uom_qty = qty
                        if fixed_price is not None:
                            existing[0].price_unit = fixed_price
                            existing[0].discount = 0.0
                        elif discount_percent:
                            existing[0].discount = float(discount_percent)
                    else:
                        vals_line = {'product_id': product.id, 'product_uom_qty': qty}
                        if fixed_price is not None:
                            vals_line['price_unit'] = fixed_price
                        elif discount_percent:
                            vals_line['discount'] = float(discount_percent)
                        order.write({'order_line': [(0, 0, vals_line)]})
                reused = True
            else:
                order_lines = []
                for product, qty, fixed_price in resolved:
                    vals_line = {'product_id': product.id, 'product_uom_qty': qty}
                    if fixed_price is not None:
                        vals_line['price_unit'] = fixed_price
                    elif discount_percent:
                        vals_line['discount'] = float(discount_percent)
                    order_lines.append((0, 0, vals_line))
                order = SaleOrder.create({
                    'partner_id': partner.id,
                    'pricelist_id': pricelist.id,
                    'order_line': order_lines,
                    'state': 'draft',
                })
                reused = False

            # ── GARANTÍA: Lista Mayorista SIEMPRE ──
            # Odoo pisa el pricelist del pedido con el del partner (pricelist_id se
            # recomputa desde partner_id). Bug real: partners CF re-etiquetados
            # mayorista (ej. Sandra) tenían L.C 1 → la cotización salía con precios
            # de consumidor final. Forzamos la Lista Mayorista, recomputamos el
            # precio de cada línea desde esa lista, y reaplicamos el descuento
            # (cambiar el pricelist lo resetea). Las líneas con precio FIJO de promo
            # se saltean (mantienen su precio cerrado).
            if order.pricelist_id.id != pricelist.id:
                order.pricelist_id = pricelist.id
                for line in order.order_line:
                    if line.product_id.id in fixed_price_pids:
                        continue
                    try:
                        line.price_unit = pricelist._get_product_price(
                            line.product_id, line.product_uom_qty or 1.0)
                    except Exception:
                        pass
            if discount_percent and order.order_line:
                # El 20% (u otro %) NO se aplica a las líneas con precio de promo cerrado.
                order.order_line.filtered(
                    lambda l: l.product_id.id not in fixed_price_pids
                ).write({'discount': float(discount_percent)})

            # Forzar el precio fijo de promo por si Odoo lo recomputó desde el
            # pricelist al setear product/pricelist (última palabra sobre esas líneas).
            if fixed_price_pids:
                for product, qty, fixed_price in resolved:
                    if fixed_price is None:
                        continue
                    fp_lines = order.order_line.filtered(
                        lambda l: l.product_id.id == product.id)
                    if fp_lines:
                        fp_lines.write({'price_unit': fixed_price, 'discount': 0.0})

            if note:
                order.note = note
            order.opportunity_id = opp.id
        except Exception as e:
            _logger.exception("Error creando/actualizando sale.order: %s", e)
            return {"error": f"No se pudo armar la cotización: {e}"}

        # 3) Fase + reset cadencia + chatter
        try:
            opp.write({'agent_strategy_phase': 'phase_2_quoted', 'agent_managed': True})
            mem = env['cristal.agent.memory'].sudo().search(
                [('partner_id', '=', partner.id)], limit=1)
            if mem:
                mem.last_cadence_step_executed = -1
        except Exception:
            pass
        try:
            note_disc = ' (20% off 1ra compra)' if discount_percent else ''
            opp.message_post(body=(
                "Cotización <b>%s</b> actualizada por Claudio: $%s%s. "
                "Pendiente de confirmación." % (
                    order.name, '{:,.0f}'.format(order.amount_total), note_disc)))
        except Exception:
            pass

        # 4) Mínimo de compra (piso duro + upsell)
        total = order.amount_total
        line_details = [{
            'product': l.product_id.display_name,
            'qty': l.product_uom_qty,
            'price_unit': l.price_unit,
            'subtotal': l.price_subtotal,
        } for l in order.order_line]

        if total < self.COMPRA_PISO:
            return {
                "ok": False,
                "blocked_min_compra": True,
                "order_id": order.id,
                "total_amount": total,
                "needs_upsell": True,
                "sin_stock": sin_stock or None,
                "problems": problems or None,
                "lines": line_details,
                "message_for_bot": (
                    f"El total va ${total:,.0f}, por debajo del PISO de "
                    f"${self.COMPRA_PISO:,.0f}. NO se puede cotizar ni enviar por "
                    f"menos. Comunicá que la compra mínima es ${self.COMPRA_MIN:,.0f} "
                    f"y hacé UPSELL (sumá productos) para llegar. Cuando supere el "
                    f"piso, volvé a llamar create_sale_order con la lista completa."),
            }

        upsell = None
        if total < self.COMPRA_MIN:
            falta = self.COMPRA_MIN - total
            upsell = (
                f"El total va ${total:,.0f}. La compra mínima es ${self.COMPRA_MIN:,.0f} "
                f"(faltan ${falta:,.0f}). COMUNICÁ el mínimo y hacé UPSELL para llegar "
                f"a ${self.COMPRA_MIN:,.0f}. Si el cliente no quiere sumar, se puede "
                f"enviar igual (supera el piso de ${self.COMPRA_PISO:,.0f}).")

        # Promo muestras gratis (+$60.000)
        SAMPLES_THRESHOLD = 60000.0
        if total >= SAMPLES_THRESHOLD:
            samples_hint = (
                f"El total (${total:,.0f}) supera ${SAMPLES_THRESHOLD:,.0f} → van 3 "
                f"MUESTRAS GRATIS. Llamá add_free_samples(partner_id={partner.id}) "
                f"para agregarlas y comunicáselas al cliente.")
        else:
            falta_s = SAMPLES_THRESHOLD - total
            samples_hint = (
                f"Faltan ${falta_s:,.0f} para llegar a ${SAMPLES_THRESHOLD:,.0f} y "
                f"ganar 3 MUESTRAS GRATIS de productos que no lleva. Usalo de upsell.")

        return {
            "ok": True,
            "order_id": order.id,
            "order_name": order.name,
            "partner": partner.name,
            "pricelist": pricelist.name,
            "total_amount": order.amount_total,
            "currency": order.currency_id.name,
            "opportunity_id": opp.id,
            "reused_draft": reused,
            "lines": line_details,
            "sin_stock": sin_stock or None,
            "upsell": upsell,
            "samples_hint": samples_hint,
            "previous_purchases": prev_purchases,
            "first_purchase_blocked": first_purchase_blocked,
            "first_purchase_note": (
                f"⚠️ Este cliente YA compró {prev_purchases} vez/veces: NO corresponde el "
                f"20% de primera compra, lo saqué. Está cotizado a precio de nivel normal. "
                f"NO le digas que le aplicaste el 20% ni menciones 'primera compra'."
            ) if first_purchase_blocked else None,
            # Resumen LITERAL del pedido real (para que el bot lo copie TEXTUAL y NO
            # invente productos/total de memoria — caso Silvia: dijo 6 productos y
            # $64.732 cuando el pedido real tenía 4 productos + bidones y $59.400).
            "client_summary": (
                "\n".join(
                    f"• {d['qty']:g} {d['product']} — ${d['subtotal']:,.0f}"
                    for d in line_details)
                + f"\nTOTAL: ${order.amount_total:,.0f}"
            ),
            "client_summary_note": (
                "⚠️ OBLIGATORIO: detallá al cliente EXACTAMENTE lo que dice `client_summary` "
                "(esos productos, esas cantidades y ese TOTAL), TEXTUAL. PROHIBIDO agregar "
                "productos, cambiar cantidades o recalcular el total de memoria. El total "
                "es SIEMPRE el de esta tool; el detalle fiel es el PDF (adjuntalo siempre)."
            ),
            "problems": problems if problems else None,
            "summary": (
                f"Cotización {order.name} ({'actualizada' if reused else 'nueva'}, draft) "
                f"para {partner.name}. Total: ${order.amount_total:,.2f}. "
                f"{'⚠️ UPSELL: ' + upsell if upsell else ''} "
                f"{'⚠️ SIN STOCK: ' + ', '.join(sin_stock) if sin_stock else ''} "
                f"Pasale order_id={order.id} a generate_quote_pdf."),
        }
