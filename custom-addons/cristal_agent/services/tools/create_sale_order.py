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


class _RouteBelowMin(Exception):
    """Pedido de ruta por debajo del mínimo: dispara el rollback del savepoint
    (no se crea nada). args[0] = dict con el detalle para responderle al bot."""


def _fmt_money(value):
    return '${:,.0f}'.format(value or 0).replace(',', '.')


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
        "BIDONES: el granel va en bidones de 20 L con recambio (se canjean por vacíos con "
        "tapa: al recibir el envío o al retirar); si el cliente no tiene vacíos para el "
        "recambio, pasá bidones_nuevos=<cuántos le faltan> y la tool cobra el bidón "
        "correcto (NUNCA agregues bidones como línea de producto). Leé SIEMPRE "
        "'bidones_note' y decíselo al cliente. "
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
            "bidones_nuevos": {
                "type": "integer",
                "description": "Cuántos bidones de 20 L NUEVOS hay que cobrarle porque no "
                               "tiene vacíos con tapa para canjear (0 = tiene todos). Pasalo "
                               "cuando el cliente te lo dijo; la tool agrega el cargo sola "
                               "al precio correcto. Si todavía no lo sabés, no lo pases "
                               "(y preguntale: ver bidones_note).",
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

    # ───────────────────────── Ruta del camión (v1.32) ─────────────────────────
    def _route_context(self, env, config, partner):
        """Clasifica al partner para la ruta. El circuito del partner (etiqueta o
        manual) manda sobre la ciudad."""
        info = env['cristal.agent.circuit'].sudo().classify_city(partner.city)
        circuit = partner.truck_circuit_id or (
            info['circuit'] if info['kind'] == 'circuit' else False)
        canonical = info.get('canonical') or partner.city
        if circuit:
            return {'kind': 'circuit', 'circuit': circuit, 'canonical': canonical,
                    'departure': circuit.get_next_departure()}
        if info['kind'] == 'rio_cuarto':
            return {'kind': 'rio_cuarto', 'canonical': canonical}
        return {'kind': 'fuera_zona', 'canonical': canonical}

    def _freight_product(self, env, config):
        if config.route_freight_product_id:
            return config.route_freight_product_id
        return env['product.product'].sudo().search(
            [('default_code', '=', 'FLETE-ZONA')], limit=1)

    def _bidon_product(self, env, config):
        """Producto que se cobra por cada bidón de 20 L nuevo ([DA0355])."""
        if config and config.bidon_product_id:
            return config.bidon_product_id
        return env['product.product'].sudo().search(
            [('default_code', '=', 'DA0355')], limit=1)

    # ───────────────────────── Bidones (v1.33) ─────────────────────────
    # Reclamo real: clientes que fueron a retirar sin saber que el granel va en
    # bidones de 20 L con recambio y que, si no hay vacíos para canjear, se cobra
    # ("no me dijiste que el bidón sale $3500"). Y cuando Claudio lo cargaba solo,
    # usaba un producto equivocado (bidón c/canilla 25 L a $10.864).
    def _apply_bidones(self, env, config, order, bidones_nuevos):
        """Deja la línea de bidones nuevos = bidones_nuevos, a precio fijo de config.
        bidones_nuevos None = no se sabe todavía (no toca nada)."""
        if bidones_nuevos is None:
            return
        product = self._bidon_product(env, config)
        if not product:
            return
        order.cristal_bidones_answered = True
        qty = max(0, int(bidones_nuevos))
        lines = order.order_line.filtered(lambda l: l.product_id == product)
        if not qty:
            lines.unlink()
            return
        price = config.bidon_price if config else 3500.0
        if lines:
            lines[1:].unlink()
            lines[:1].write({'product_uom_qty': qty, 'price_unit': price, 'discount': 0.0})
        else:
            order.write({'order_line': [(0, 0, {
                'product_id': product.id, 'product_uom_qty': qty,
                'price_unit': price, 'discount': 0.0})]})
        # Última palabra sobre el precio (la lista o el 20% no lo tocan).
        order.order_line.filtered(lambda l: l.product_id == product).write(
            {'price_unit': price, 'discount': 0.0})

    def _bidones_info(self, env, config, order):
        """Cuántos bidones de 20 L lleva el pedido y el texto OBLIGATORIO para el
        cliente. Se incluye en client_summary, así sale en todas las cotizaciones."""
        product = self._bidon_product(env, config)
        granel_l = sum(l.product_uom_qty for l in order.order_line
                       if l.product_id != product and self._es_granel(l.product_id))
        needed = int(round(granel_l / self.GRANEL_MIN_L)) if granel_l else 0
        if not needed:
            return None
        price = config.bidon_price if config else 3500.0
        nuevos = int(sum(order.order_line.filtered(
            lambda l: l.product_id == product).mapped('product_uom_qty')))
        answered = bool(order.cristal_bidones_answered)
        recambio = max(0, needed - nuevos)
        bid = f"{needed} bidón de 20 L" if needed == 1 else f"{needed} bidones de 20 L"
        vacios = "1 bidón vacío con tapa" if needed == 1 else f"{needed} bidones vacíos con tapa"
        # Recambio = CANJE: con envío, los vacíos se entregan al recibir el pedido;
        # si retira, los lleva a la planta. No es "traerlos" siempre.
        if not answered:
            summary = (f"Envases: va en {bid}, con recambio: se canjean por {vacios} "
                       f"(si se lo enviamos, los entrega al recibir el pedido; si retira, "
                       f"los lleva a la planta). Si no tiene vacíos para canjear, cada "
                       f"bidón nuevo sale {_fmt_money(price)}.")
        elif nuevos:
            summary = (f"Envases: {bid}: {nuevos} nuevo(s) a {_fmt_money(price)} c/u (ya "
                       f"incluido en el total)"
                       + (f" y {recambio} de recambio (se canjea(n) por vacíos con tapa)"
                          if recambio else "")
                       + ".")
        else:
            summary = (f"Envases: {bid} de recambio: se canjean por {vacios} (sin cargo).")
        note = "⚠️ BIDONES — OBLIGATORIO decirlo SIEMPRE, antes del total: " + summary
        if not answered:
            note += (f" Todavía no sabés si tiene vacíos para canjear: preguntale si tiene "
                     f"los {vacios} para el recambio (con el mismo trato que venís usando: "
                     f"vos o usted) y volvé a llamar create_sale_order con "
                     f"bidones_nuevos=<cuántos le faltan> (0 si tiene todos).")
        return {'needed': needed, 'nuevos': nuevos, 'answered': answered,
                'price': price, 'summary': summary, 'note': note}

    def _route_tag(self, env, circuit):
        """Etiqueta de orden (crm.tag) del circuito, ej: 'Ruta Sur-Oeste'."""
        Tag = env['crm.tag'].sudo()
        name = f"Ruta {circuit.name}"
        return Tag.search([('name', '=', name)], limit=1) or Tag.create({'name': name})

    def _apply_route(self, env, config, route_ctx, order):
        """Aplica las reglas de la ruta sobre la orden (dentro del savepoint).
        Mínimo y envío gratis se miden sobre el subtotal de PRODUCTOS sin IVA,
        después de la lista y SIN la línea de flete. Devuelve un dict; si
        'below_min' viene en True, el llamador hace rollback."""
        circuit = route_ctx['circuit']
        departure = route_ctx.get('departure')
        freight_product = self._freight_product(env, config)

        # Idempotente: en un re-cotizado los umbrales pueden cambiar → se saca el
        # flete anterior y se recalcula.
        if freight_product:
            order.order_line.filtered(lambda l: l.product_id == freight_product).unlink()
        # El flete y los bidones nuevos no son "productos": no suman para el mínimo
        # ni para el envío gratis.
        non_products = freight_product | self._bidon_product(env, config)
        product_lines = order.order_line.filtered(lambda l: l.product_id not in non_products)
        product_subtotal = sum(product_lines.mapped('price_subtotal'))

        rescate = bool(departure and departure.state == 'rescate')
        free_from = (departure.rescue_free_shipping_from if rescate
                     else config.route_free_shipping_from)
        block = {
            'circuit': circuit.name,
            'town': route_ctx['canonical'],
            'departure_id': departure.id if departure else False,
            'delivery_date': departure.date.isoformat() if departure else None,
            'product_subtotal': product_subtotal,
            'min_order': config.route_min_order,
            'free_shipping_from': free_from,
            'rescate': rescate,
            'lines': [{'product': l.product_id.display_name, 'qty': l.product_uom_qty, 'price_unit': l.price_unit,
                       'subtotal': l.price_subtotal} for l in product_lines],
        }
        if product_subtotal < config.route_min_order:
            block['below_min'] = True
            block['missing'] = config.route_min_order - product_subtotal
            # Los bidones se informan igual (se calcula antes del rollback).
            bid_info = self._bidones_info(env, config, order)
            block['bidones_note'] = bid_info['note'] if bid_info else None
            return block

        freight = 0.0
        if product_subtotal < free_from and freight_product:
            freight = config.route_freight_amount
            order.write({'order_line': [(0, 0, {
                'product_id': freight_product.id, 'product_uom_qty': 1,
                'price_unit': freight, 'discount': 0.0})]})
            # Última palabra sobre el flete: la Lista Mayorista tiene una regla global
            # de -20% (item 9740) que Odoo podría aplicar como precio o como descuento.
            order.order_line.filtered(lambda l: l.product_id == freight_product).write(
                {'price_unit': freight, 'discount': 0.0})
        block['freight'] = freight
        block['missing_for_free_shipping'] = (free_from - product_subtotal) if freight else 0.0

        vals = {'route_departure_id': departure.id if departure else False,
                'tag_ids': [(4, self._route_tag(env, circuit).id)]}
        if departure:
            vals['commitment_date'] = departure.get_commitment_datetime()
        order.write(vals)
        if rescate and departure.courtesy_product_id:
            block['courtesy_product'] = departure.courtesy_product_id.display_name
        return block

    def _route_below_min_response(self, block, sin_stock, problems):
        return {
            "ok": False,
            "blocked_route_min": True,
            "order_created": False,
            "circuit": block['circuit'],
            "product_subtotal": block['product_subtotal'],
            "min_order": block['min_order'],
            "missing": block['missing'],
            "lines": block['lines'],
            "sin_stock": sin_stock or None,
            "problems": problems or None,
            "bidones_note": block.get('bidones_note'),
            "message_for_bot": (
                f"NO creé la cotización: los productos suman "
                f"{_fmt_money(block['product_subtotal'])} y el pedido mínimo de la "
                f"ruta ({block['circuit']}) es {_fmt_money(block['min_order'])} (sin "
                f"contar flete). Faltan {_fmt_money(block['missing'])}. NO pierdas la venta: "
                f"sugerí productos complementarios para completar el mínimo y volvé a "
                f"llamar create_sale_order con la lista completa."),
        }

    def _route_result_fields(self, block):
        out = {
            "route": True,
            "circuit": block['circuit'],
            "town": block['town'],
            "delivery_date": block.get('delivery_date'),
            "product_subtotal": block['product_subtotal'],
            "freight": block['freight'],
            "free_shipping_from": block['free_shipping_from'],
            "missing_for_free_shipping": block['missing_for_free_shipping'] or None,
            "rescate": block['rescate'],
            "courtesy_product": block.get('courtesy_product'),
        }
        freight_txt = (f"flete {_fmt_money(block['freight'])} (faltan "
                       f"{_fmt_money(block['missing_for_free_shipping'])} de productos para "
                       f"que el envío sea sin cargo)" if block['freight']
                       else "envío sin cargo")
        out["route_note"] = (
            f"Pedido de ruta ({block['circuit']}): productos "
            f"{_fmt_money(block['product_subtotal'])}, {freight_txt}. "
            + ("Salida en RESCATE: ofrecé el producto de cortesía. "
               if block['rescate'] and block.get('courtesy_product') else "")
            + "La fecha de paso y el cierre de preventa salen de get_route_info: no "
              "prometas otra. Ya escalé el pedido a Joaco.")
        return out

    def _escalate_route_order(self, env, run, partner, order, route_ctx, block):
        departure = route_ctx.get('departure')
        dep_txt = departure.date.strftime('%d/%m') if departure else 'SIN SALIDA PROGRAMADA'
        freight_txt = _fmt_money(block['freight']) if block['freight'] else 'sin cargo'
        msg = (
            f"🚚 Pedido de ruta {order.name} — {partner.name} ({block['town']}, circuito "
            f"{block['circuit']}). Productos {_fmt_money(block['product_subtotal'])}, "
            f"flete {freight_txt}, entrega jueves {dep_txt}. Queda en borrador para revisar.")
        self._escalate(env, run, partner, msg)

    def _escalate_fuera_zona(self, env, run, partner, order, route_ctx):
        msg = (
            f"📍 {partner.name} es de {route_ctx['canonical']}, FUERA de los circuitos de "
            f"la ruta. Cotización {order.name} en borrador: definí cómo le llega "
            f"(retiro en Río Cuarto o transporte a su cargo).")
        self._escalate(env, run, partner, msg)

    def _escalate(self, env, run, partner, msg):
        tool = ToolRegistry.get('escalate_to_joaco')
        if not tool:
            return
        try:
            tool.execute(env=env, run=run, message=msg, related_partner_id=partner.id)
        except Exception as e:
            _logger.warning("No pude escalar el pedido de ruta a Joaco: %s", e)

    def _mark_fuera_zona(self, env, partner):
        vals = {}
        if partner.agent_zone != 'fuera_zona':
            vals['agent_zone'] = 'fuera_zona'
        fz_tag = env['res.partner.category'].sudo().search(
            [('name', '=', 'Fuera de zona')], limit=1)
        if fz_tag and fz_tag not in partner.category_id:
            vals['category_id'] = [(4, fz_tag.id)]
        if vals:
            partner.write(vals)

    # ─────────────────────────────── Main ───────────────────────────────
    def _execute(self, env, run=None, partner_id=None, lines=None,
                 pricelist_name='Lista Mayorista', note=None,
                 discount_percent=None, bidones_nuevos=None, **kwargs):
        if not (partner_id and lines):
            return {"error": "partner_id y lines son obligatorios"}

        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        # ── RUTA DEL CAMIÓN (v1.32): la localidad es obligatoria para cotizar ──
        config = env['cristal.agent.config'].sudo().get_active()
        route_ctx = None
        if config and config.enable_truck_route:
            if not (partner.city or '').strip():
                return {
                    "ok": False,
                    "needs_city": True,
                    "blocked_no_city": True,
                    "message_for_bot": (
                        "NO puedo cotizar sin la LOCALIDAD del cliente. Preguntale de qué "
                        "localidad es su comercio y guardala con update_partner(city=...). "
                        "Después volvé a llamar create_sale_order."),
                }
            route_ctx = self._route_context(env, config, partner)

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
        # El bidón nuevo tiene precio fijo: ni la lista ni el 20% lo tocan.
        bidon_product = self._bidon_product(env, config)
        if bidon_product:
            fixed_price_pids.add(bidon_product.id)
        problems = []
        sin_stock = []
        bidon_adjustments = []  # granel redondeado a múltiplo de 20 L (bidones)
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
            # Granel: se vende en BIDONES de 20 L → la cantidad DEBE ser múltiplo
            # de 20 (no existe medio bidón: nada de 10, 30, 50). Si no lo es (o es
            # < 20), la redondeamos HACIA ARRIBA al próximo múltiplo de 20 y avisamos.
            if self._es_granel(product):
                mult = self.GRANEL_MIN_L
                adj = int(-(-qty // mult)) * mult  # ceil(qty/mult) * mult
                if adj != qty:
                    bidon_adjustments.append(
                        f"{product.display_name}: {qty:g} L → {adj} L "
                        f"(granel en bidones de {mult} L)")
                    qty = float(adj)
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

        # 2) Oportunidad + cotización ÚNICA (reusar borrador si existe).
        # Todo va dentro de un SAVEPOINT: si es un pedido de ruta que no llega al
        # mínimo, se hace rollback y NO queda nada creado (ni orden ni oportunidad).
        # Así el subtotal sin IVA sale del cálculo real de Odoo, no de una simulación.
        route_block = None
        try:
            with env.cr.savepoint():
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

                # Bidones nuevos (si el cliente ya dijo cuántos le faltan).
                self._apply_bidones(env, config, order, bidones_nuevos)

                if note:
                    order.note = note
                order.opportunity_id = opp.id

                # ── Ruta del camión: mínimo, flete, fecha de entrega, salida, etiqueta ──
                if route_ctx and route_ctx['kind'] == 'circuit':
                    route_block = self._apply_route(env, config, route_ctx, order)
                    if route_block.get('below_min'):
                        # Rollback del savepoint: no queda orden ni oportunidad creada.
                        raise _RouteBelowMin(route_block)
        except _RouteBelowMin as e:
            env.invalidate_all()
            return self._route_below_min_response(e.args[0], sin_stock, problems)
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

        # 4) Mínimo de compra (piso duro + upsell). En RUTA el mínimo ya se validó en
        #    el savepoint (sobre subtotal de productos sin IVA ni flete): no se repite.
        is_route = bool(route_block)
        total = order.amount_total
        line_details = [{
            'product': l.product_id.display_name,
            'qty': l.product_uom_qty,
            'price_unit': l.price_unit,
            'subtotal': l.price_subtotal,
        } for l in order.order_line]
        # Bidones: se informan SIEMPRE, también cuando el pedido queda bajo el mínimo.
        bid_info = self._bidones_info(env, config, order)

        if not is_route and total < self.COMPRA_PISO:
            return {
                "ok": False,
                "blocked_min_compra": True,
                "order_id": order.id,
                "total_amount": total,
                "needs_upsell": True,
                "sin_stock": sin_stock or None,
                "problems": problems or None,
                "lines": line_details,
                "bidones_note": bid_info['note'] if bid_info else None,
                "message_for_bot": (
                    f"El total va {_fmt_money(total)}, por debajo del PISO de "
                    f"{_fmt_money(self.COMPRA_PISO)}. NO se puede cotizar ni enviar por "
                    f"menos. Comunicá que la compra mínima es {_fmt_money(self.COMPRA_MIN)} "
                    f"y hacé UPSELL (sumá productos) para llegar. Cuando supere el "
                    f"piso, volvé a llamar create_sale_order con la lista completa."),
            }

        upsell = None
        if not is_route and total < self.COMPRA_MIN:
            falta = self.COMPRA_MIN - total
            upsell = (
                f"El total va {_fmt_money(total)}. La compra mínima es {_fmt_money(self.COMPRA_MIN)} "
                f"(faltan {_fmt_money(falta)}). COMUNICÁ el mínimo y hacé UPSELL para llegar "
                f"a {_fmt_money(self.COMPRA_MIN)}. Si el cliente no quiere sumar, se puede "
                f"enviar igual (supera el piso de {_fmt_money(self.COMPRA_PISO)}).")


        result = {
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
                    f"• {d['qty']:g} {d['product']} — {_fmt_money(d['subtotal'])}"
                    for d in line_details)
                + (f"\n{bid_info['summary']}" if bid_info else "")
                + f"\nTOTAL: {_fmt_money(order.amount_total)}"
            ),
            "bidones": {k: bid_info[k] for k in ('needed', 'nuevos', 'answered', 'price')}
            if bid_info else None,
            "bidones_note": bid_info['note'] if bid_info else None,
            "client_summary_note": (
                "⚠️ OBLIGATORIO: detallá al cliente EXACTAMENTE lo que dice `client_summary` "
                "(esos productos, esas cantidades y ese TOTAL), TEXTUAL. PROHIBIDO agregar "
                "productos, cambiar cantidades o recalcular el total de memoria. El total "
                "es SIEMPRE el de esta tool; el detalle fiel es el PDF (adjuntalo siempre)."
            ),
            "bidon_adjustments": bidon_adjustments or None,
            "bidon_note": (
                "Ajusté cantidades de granel al múltiplo de 20 L (se vende en bidones "
                "de 20 L, no hay fracciones): " + "; ".join(bidon_adjustments)
                + ". Avisale al cliente el ajuste."
            ) if bidon_adjustments else None,
            "problems": problems if problems else None,
            "summary": (
                f"Cotización {order.name} ({'actualizada' if reused else 'nueva'}, draft) "
                f"para {partner.name}. Total: ${order.amount_total:,.2f}. "
                f"{'⚠️ UPSELL: ' + upsell if upsell else ''} "
                f"{'⚠️ SIN STOCK: ' + ', '.join(sin_stock) if sin_stock else ''} "
                f"Pasale order_id={order.id} a generate_quote_pdf."),
        }

        # 5) Ruta del camión: condiciones de envío + escalamiento a Joaco
        if is_route:
            result.update(self._route_result_fields(route_block))
            self._escalate_route_order(env, run, partner, order, route_ctx, route_block)
        elif route_ctx and route_ctx['kind'] == 'rio_cuarto':
            result['route_note'] = (
                "Cliente de Río Cuarto: reparto normal SOLO por la mañana y NO los jueves "
                "(ese día sale el camión de la ruta). No ofrezcas ENTREGA en jueves; el "
                "RETIRO en planta el jueves SÍ se puede, en el horario oficial.")
        elif route_ctx and route_ctx['kind'] == 'fuera_zona':
            self._mark_fuera_zona(env, partner)
            self._escalate_fuera_zona(env, run, partner, order, route_ctx)
            result['route_note'] = (
                f"{route_ctx['canonical']} está FUERA de los 4 circuitos de la ruta. NO "
                f"ofrezcas condiciones de envío (ni mínimo de ruta, ni flete, ni fecha): ya "
                f"escalé a Joaco para que defina cómo le llega.")
        return result
