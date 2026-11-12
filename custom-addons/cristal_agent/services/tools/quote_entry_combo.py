# -*- coding: utf-8 -*-
"""
Tool: quote_entry_combo (v1.68 — 3 combos de entrada)

Joaco (12/11/2026): "analizá armar 3 combos… y que con preguntas le ofrezca el que más se
adecue"; precios "60, 75, 107". Armados con las primeras compras de 115 clientes nuevos
(mediana $70.000; jabón, suavizante, detergente y lavandina en la mayoría; el desengrasante
cáustico casi no se recompra). Cada combo cuesta menos que sus productos sueltos.

El precio del combo se reparte entre sus líneas (precio fijo por litro), y si al cliente le
corresponde el 20 % de primera compra (Río Cuarto / Las Higueras o retiro, y nunca compró)
se aplica sobre el precio del combo. Los bidones, el flete y el mínimo de la ruta los
resuelve create_sale_order como siempre.
"""
import logging

from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

# código → (nombre, precio, [(product_id, default_code, litros)], para quién)
ENTRY_COMBOS = {
    'prueba': ("Combo Prueba", 60000.0, [
        (12036, None, 20), (5714, 'PQ0213', 20), (5878, 'PQ0246', 20),
        (5694, 'PQ0114', 20), (5755, 'PQ0119', 20)],
        "arranca de cero o quiere invertir poco (kiosco, almacén chico)"),
    'arranque': ("Combo Arranque", 75000.0, [
        (12036, None, 20), (5714, 'PQ0213', 20), (5878, 'PQ0246', 20),
        (5885, 'PQ0243', 20), (5694, 'PQ0114', 20), (5755, 'PQ0119', 20),
        (6122, 'PQ0169', 20)],
        "almacén que quiere surtido; llega al envío gratis y al mínimo de la ruta"),
    'completo': ("Combo Completo", 107000.0, [
        (12036, None, 40), (5714, 'PQ0213', 20), (5878, 'PQ0246', 20),
        (5885, 'PQ0243', 20), (5694, 'PQ0114', 20), (5755, 'PQ0119', 20),
        (6122, 'PQ0169', 20), (5651, 'PQ0311', 20)],
        "ya vende suelto, lavadero o revendedor con clientela"),
}
PRICELIST = 'Lista Mayorista'


def resolve_combo(env, code):
    """[(product, litros)] del combo, buscando por id y si no por código."""
    name, price, items, who = ENTRY_COMBOS[code]
    Product = env['product.product'].sudo()
    out = []
    for pid, dcode, qty in items:
        p = Product.browse(pid).exists()
        if not p and dcode:
            p = Product.search([('default_code', '=', dcode)], limit=1)
        if p:
            out.append((p, float(qty)))
    return out


def combo_catalog_text(env):
    """Bloque para el prompt: qué trae cada combo y cuánto sale suelto."""
    pl = env['product.pricelist'].sudo().search([('name', '=', PRICELIST)], limit=1)
    rows = []
    for code, (name, price, _items, who) in ENTRY_COMBOS.items():
        lines = resolve_combo(env, code)
        loose = 0.0
        parts = []
        for p, qty in lines:
            try:
                loose += pl._get_product_price(p, qty) * qty if pl else 0.0
            except Exception:  # noqa: BLE001
                pass
            parts.append(f"{qty:g} L {p.name}")
        ahorro = f" (suelto ${loose:,.0f})".replace(',', '.') if loose > price else ""
        rows.append(f"- **{name}** `{code}` — ${price:,.0f}".replace(',', '.') + ahorro +
                    f": {', '.join(parts)}. Para quien {who}.")
    return "\n".join(rows)


@ToolRegistry.register
class QuoteEntryCombo(AgentTool):
    name = "quote_entry_combo"
    description = (
        "Cotiza uno de los 3 COMBOS DE ENTRADA para clientes que arrancan: 'prueba' "
        "($60.000), 'arranque' ($75.000) o 'completo' ($107.000). Elegí el combo con las "
        "preguntas del bloque COMBOS DE ENTRADA y llamá esta tool (no armes las líneas a "
        "mano). Aplica sola el 20 % de primera compra si corresponde. Pasá bidones_nuevos si "
        "ya sabés cuántos bidones vacíos le faltan, y delivery_mode='retiro' si retira."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer"},
            "combo": {"type": "string", "enum": list(ENTRY_COMBOS)},
            "bidones_nuevos": {"type": "integer",
                               "description": "Bidones de 20 L que no tiene (se cobran)."},
            "delivery_mode": {"type": "string", "enum": ["envio", "retiro"]},
        },
        "required": ["partner_id", "combo"],
    }

    def _execute(self, env, run=None, partner_id=None, combo=None, bidones_nuevos=None,
                 delivery_mode=None, **kwargs):
        if combo not in ENTRY_COMBOS:
            return {"error": "combo tiene que ser prueba, arranque o completo"}
        partner = env['res.partner'].sudo().browse(int(partner_id or 0))
        if not partner.exists():
            return {"error": "partner_id no existe"}
        name, price, _items, _who = ENTRY_COMBOS[combo]
        lines = resolve_combo(env, combo)
        if not lines:
            return {"error": f"No encontré los productos del {name}: escalá a Joaco."}
        pl = env['product.pricelist'].sudo().search([('name', '=', PRICELIST)], limit=1)
        loose = {}
        for p, qty in lines:
            try:
                loose[p.id] = pl._get_product_price(p, qty) if pl else 0.0
            except Exception:  # noqa: BLE001
                loose[p.id] = 0.0
        total_loose = sum(loose[p.id] * qty for p, qty in lines)
        if total_loose <= 0:
            return {"error": "No pude calcular los precios de la lista: escalá a Joaco."}
        # 20 % de primera compra: nunca compró y es de Río Cuarto / Las Higueras o retira.
        from ..helpers import first_purchase_discount_status
        prev = env['sale.order'].sudo().search_count([
            ('partner_id', 'child_of', partner.commercial_partner_id.id),
            ('state', 'in', ('sale', 'done'))])
        status = first_purchase_discount_status(env, partner)[0]
        pickup = (delivery_mode or '') == 'retiro'
        first = (not prev) and (status == 'allowed' or pickup)
        target = price * (0.8 if first else 1.0)
        factor = target / total_loose
        order_lines = [{'product_id': p.id, 'qty': qty,
                        'price_unit': round(loose[p.id] * factor, 2)} for p, qty in lines]
        cso = ToolRegistry.get('create_sale_order')
        res = cso.execute(env=env, run=run, partner_id=partner.id, lines=order_lines,
                          bidones_nuevos=bidones_nuevos, delivery_mode=delivery_mode,
                          note=f"{name}" + (" con 20 % de primera compra" if first else "")) or {}
        if res.get('ok'):
            ahorro = max(total_loose - price, 0)
            res['combo'] = {
                'nombre': name, 'precio_combo': price, 'precio_suelto': round(total_loose),
                'ahorro_vs_suelto': round(ahorro), 'primera_compra_20': first,
                'precio_final_productos': round(target),
                'trae': [f"{qty:g} L {p.name}" for p, qty in lines]}
            res['combo_note'] = (
                f"Cotizado el {name}: ${price:,.0f}".replace(',', '.') +
                (f" − 20 % de primera compra = ${target:,.0f}".replace(',', '.') if first else "") +
                (f" (suelto sale ${total_loose:,.0f}, ahorra ${ahorro:,.0f})".replace(',', '.')
                 if ahorro > 0 else "") +
                ". Decile qué trae (lista literal), el precio del combo y el total de la "
                "cotización con bidones y envío (client_summary). No des precios por litro.")
        return res
