# -*- coding: utf-8 -*-
"""
Tool: create_sale_order

Crea una sale.order en estado DRAFT (borrador) para un cliente.
- Aplica la pricelist correcta según el tipo de cliente.
- Acepta líneas como lista de {product_id, qty} o {product_name, qty} (con búsqueda fuzzy).
- Devuelve order_id para que después se llame a generate_quote_pdf.

IMPORTANTE: queda en draft. Joaco la revisa y confirma antes de mandarla al cliente.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class CreateSaleOrder(AgentTool):
    name = "create_sale_order"
    description = (
        "Crea una cotización (sale.order) en estado DRAFT para el cliente. "
        "Pasale partner_id y una lista de líneas: cada línea con product_id+qty o product_name+qty "
        "(la tool busca el producto por nombre con fuzzy match). "
        "Devuelve order_id para luego generar PDF con generate_quote_pdf y mandar por WA. "
        "Pasá discount_percent=20 para el 20% OFF de PRIMERA COMPRA (se aplica a todas las líneas). "
        "La cotización queda en draft — Joaco la revisa y confirma antes de cerrarla."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {
                "type": "integer",
                "description": "ID del partner cliente.",
            },
            "lines": {
                "type": "array",
                "description": "Lista de líneas de la cotización. Cada una: "
                               "{product_id (int) + qty (number)} o {product_name (str) + qty (number)}.",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer"},
                        "product_name": {"type": "string"},
                        "qty": {"type": "number"},
                    },
                },
            },
            "pricelist_name": {
                "type": "string",
                "description": "Nombre de pricelist a aplicar. Default: 'Lista Mayorista'.",
            },
            "note": {
                "type": "string",
                "description": "(Opcional) Nota interna que se agrega a la cotización.",
            },
            "discount_percent": {
                "type": "number",
                "description": "Descuento % a aplicar a TODAS las líneas. Usá 20 para el "
                               "20% OFF de primera compra. Default: sin descuento.",
            },
        },
        "required": ["partner_id", "lines"],
    }

    def _execute(self, env, run=None, partner_id=None, lines=None,
                 pricelist_name='Lista Mayorista', note=None,
                 discount_percent=None, **kwargs):
        if not (partner_id and lines):
            return {"error": "partner_id y lines son obligatorios"}

        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        # Resolver pricelist
        Pricelist = env['product.pricelist'].sudo()
        pricelist = Pricelist.search([('name', '=', pricelist_name)], limit=1)
        if not pricelist:
            # Fallback a la pricelist del partner si tiene
            pricelist = partner.property_product_pricelist
        if not pricelist:
            return {"error": f"No encontré pricelist '{pricelist_name}' ni en el partner"}

        # Resolver líneas
        Product = env['product.product'].sudo()
        order_lines = []
        problems = []
        for i, ln in enumerate(lines):
            qty = float(ln.get('qty', 0))
            if qty <= 0:
                problems.append(f"Línea {i+1}: qty inválida ({qty})")
                continue

            product = None
            if ln.get('product_id'):
                product = Product.browse(int(ln['product_id']))
                if not product.exists():
                    product = None

            if not product and ln.get('product_name'):
                # Búsqueda fuzzy: dividimos por palabras (AND) para encontrar
                # variantes "fuera de orden" en el nombre.
                # Ej: 'Ariel granel' encuentra 'Detergente Ariel 200L Granel'.
                name = ln['product_name'].strip()
                words = [w for w in name.split() if len(w) > 1]

                # Estrategia A: dentro del catálogo mayorista, palabras AND
                if words:
                    domain_words = [('product_tmpl_id.is_mayorista_catalog', '=', True),
                                    ('sale_ok', '=', True)]
                    for w in words:
                        domain_words.append(('name', 'ilike', w))
                    product = Product.search(domain_words, limit=1)

                # Estrategia B: fuera del catálogo, palabras AND
                if not product and words:
                    domain_words = [('sale_ok', '=', True)]
                    for w in words:
                        domain_words.append(('name', 'ilike', w))
                    product = Product.search(domain_words, limit=1)
                    if product:
                        problems.append(
                            f"Producto '{name}' encontrado pero está FUERA del Catálogo Mayorista. "
                            f"Avisale a Joaco para que lo agregue al catálogo si corresponde."
                        )

                # Estrategia C: fallback ilike directo (por si quedó algo sin matchear)
                if not product:
                    product = Product.search([
                        ('name', 'ilike', name),
                        ('sale_ok', '=', True),
                    ], limit=1)

            if not product:
                problems.append(
                    f"Línea {i+1}: no encontré el producto "
                    f"(id={ln.get('product_id')}, name={ln.get('product_name')})"
                )
                continue

            line_vals = {
                'product_id': product.id,
                'product_uom_qty': qty,
            }
            if discount_percent:
                try:
                    line_vals['discount'] = float(discount_percent)
                except (TypeError, ValueError):
                    pass
            order_lines.append((0, 0, line_vals))

        if not order_lines:
            return {
                "error": "No se pudieron resolver líneas válidas.",
                "problems": problems,
            }

        # Crear sale.order en draft
        try:
            vals = {
                'partner_id': partner.id,
                'pricelist_id': pricelist.id,
                'order_line': order_lines,
                'state': 'draft',
            }
            if note:
                vals['note'] = note
            order = env['sale.order'].sudo().create(vals)
        except Exception as e:
            _logger.exception("Error creando sale.order: %s", e)
            return {"error": f"No se pudo crear la sale.order: {e}"}

        # ── v1.12: el bot SIEMPRE trabaja sobre una oportunidad ──
        # Vinculamos la cotización a la oportunidad abierta del cliente (o la
        # creamos si no existe) y avanzamos la fase a "Propuesta enviada". Así la
        # cotización NUNCA queda "en el aire": cuelga del lead en el CRM y el
        # pipeline refleja el avance.
        opp_id = None
        try:
            Lead = env['crm.lead'].sudo()
            opp = Lead.search([
                ('partner_id', '=', partner.id),
                ('type', '=', 'opportunity'),
                ('active', '=', True),
                ('stage_id', 'not in', [4, 13]),  # no Ganado / Perdido
            ], limit=1, order='create_date desc')
            if not opp:
                opp = Lead.create({
                    'name': partner.name or 'Cliente mayorista',
                    'partner_id': partner.id,
                    'type': 'opportunity',
                    'agent_managed': True,
                })
            order.opportunity_id = opp.id
            opp_id = opp.id
            try:
                # v1.16: marcamos agent_managed (para que el cron de seguimiento
                # la tome) y reseteamos el contador de cadencia para que el
                # seguimiento de cotización (días 1/3/7) arranque limpio.
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
                    "Cotización <b>%s</b> enviada por Claudio: $%s%s. "
                    "Pendiente de confirmación." % (
                        order.name, '{:,.0f}'.format(order.amount_total), note_disc)))
            except Exception:
                pass
        except Exception as e:
            _logger.warning("No se pudo vincular la cotización a una oportunidad: %s", e)

        # Detalle de líneas resueltas para devolver al bot
        line_details = []
        for line in order.order_line:
            line_details.append({
                'product': line.product_id.display_name,
                'qty': line.product_uom_qty,
                'price_unit': line.price_unit,
                'subtotal': line.price_subtotal,
            })

        return {
            "ok": True,
            "order_id": order.id,
            "order_name": order.name,
            "partner": partner.name,
            "pricelist": pricelist.name,
            "total_amount": order.amount_total,
            "currency": order.currency_id.name,
            "opportunity_id": opp_id,
            "lines": line_details,
            "problems": problems if problems else None,
            "summary": (
                f"Cotización {order.name} (draft) para {partner.name}, "
                f"colgada de la oportunidad #{opp_id}. "
                f"Total: ${order.amount_total:,.2f}. "
                f"Pasale el order_id={order.id} a generate_quote_pdf para mandar el PDF."
            ),
        }
