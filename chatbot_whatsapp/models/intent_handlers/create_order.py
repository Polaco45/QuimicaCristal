import json
import logging
import openai
from odoo.exceptions import UserError
from ...config.config import prompts_config, messages_config, general_config

_logger = logging.getLogger(__name__)

def add_item_to_cart(memory, product_id, quantity):
    """Agrega un item al carrito en la memoria, consolidando si ya existe."""
    cart_items = json.loads(memory.pending_order_lines or '[]')
    found = False
    for item in cart_items:
        if item.get('product_id') == product_id:
            item['quantity'] += quantity
            found = True
            break
    if not found:
        cart_items.append({'product_id': product_id, 'quantity': quantity})
    memory.write({'pending_order_lines': json.dumps(cart_items)})
    _logger.info(f"🛒 Carrito actualizado: {cart_items}")

def format_cart_for_display(env, cart_lines):
    """Función helper para formatear el carrito y mostrarlo al usuario."""
    if not cart_lines:
        return messages_config['cart_is_empty']

    product_ids = [item['product_id'] for item in cart_lines]
    products = env['product.product'].sudo().browse(product_ids)
    product_map = {p.id: p.display_name for p in products}

    summary_lines = []
    for i, item in enumerate(cart_lines, 1):
        product_name = product_map.get(item['product_id'], 'Producto no encontrado')
        summary_lines.append(f"{i}) {item['quantity']} × {product_name}")
    
    return "\n".join(summary_lines)

def handle_modificar_pedido(env, memory):
    """Prepara el mensaje para mostrar el carrito y permitir la eliminación."""
    cart_lines = json.loads(memory.pending_order_lines or '[]')
    if not cart_lines:
        memory.write({'flow_state': False})
        return messages_config['cart_is_empty']

    cart_summary = format_cart_for_display(env, cart_lines)
    memory.write({'flow_state': 'esperando_seleccion_eliminar'})
    return messages_config['cart_summary'].format(summary=cart_summary)

def lookup_product_variants(env, partner, query, limit=10):
    Product = env['product.product'].sudo()
    variants = Product.search([
        '|', ('name', 'ilike', query), ('display_name', 'ilike', query)
    ], limit=limit)
    _logger.info(f"🔍 Buscando variantes para query '{query}' — Encontradas: {len(variants)}")
    if not variants:
        raise UserError(messages_config['product_not_in_odoo'].format(query=query))

    in_stock = variants.filtered(lambda p: (p.qty_available or 0) > 0)
    if not in_stock:
        raise UserError(messages_config['product_no_stock'].format(query=query))

    pricelist = partner.property_product_pricelist
    if not pricelist:
        raise UserError(messages_config['customer_no_pricelist'])

    products_prices = pricelist._compute_price_rule(in_stock, 1.0)
    products_with_prices = []
    for v in in_stock:
        price = products_prices.get(v.id, (v.list_price, False))[0]
        products_with_prices.append({
            'id': v.id, 'name': v.display_name,
            'stock': v.qty_available, 'price': price,
        })
    _logger.info(f"📦 Variantes en stock con precio: {[p['name'] for p in products_with_prices]}")
    return products_with_prices

def create_sale_order(env, partner_id, order_lines, partner_shipping_id=None):
    """Crea la orden de venta y el lead asociado."""
    partner = env['res.partner'].browse(partner_id)
    pricelist = partner.property_product_pricelist

    description_lines = []
    order_line_vals = []
    for line in order_lines:
        product = env['product.product'].browse(line['product_id'])
        order_line_vals.append((0, 0, {
            'product_id': line['product_id'],
            'product_uom': product.uom_id.id,
            'product_uom_qty': line['quantity'],
        }))
        description_lines.append(f"  - Producto: {product.display_name}, Cantidad: {line['quantity']}")

    order_vals = {
        'partner_id': partner_id,
        'pricelist_id': pricelist.id,
        'order_line': order_line_vals
    }
    if partner_shipping_id:
        order_vals['partner_shipping_id'] = partner_shipping_id
    order = env['sale.order'].with_context(pricelist=pricelist.id).sudo().create(order_vals)
    _logger.info(f"✅ Orden creada: {order.name} para la dirección ID: {order.partner_shipping_id.id}")

    salesperson_id = partner.user_id.id or False

    lead_vals = {
        'name': f"Pedido WhatsApp: {partner.name or 'Cliente sin nombre'}",
        'partner_id': partner.id,
        'type': 'opportunity',
        'contact_name': partner.name,
        'email_from': partner.email,
        'phone': partner.phone,
        'description': "Se generó un pedido desde WhatsApp con los siguientes items:\n" + "\n".join(description_lines),
        'expected_revenue': order.amount_total,
        'user_id': salesperson_id,
    }
    
    if partner.category_id:
        full_tag_name = partner.category_id[0].name
        simple_tag_name = full_tag_name.split(' / ')[-1].strip()
        
        crm_tag = env['crm.tag'].sudo().search([('name', 'ilike', simple_tag_name)], limit=1)
        if not crm_tag:
            crm_tag = env['crm.tag'].sudo().create({'name': simple_tag_name})
            
        lead_vals['tag_ids'] = [(6, 0, [crm_tag.id])]
        _logger.info(f"🏷️  Etiqueta '{simple_tag_name}' asignada al lead.")

    lead = env['crm.lead'].sudo().create(lead_vals)
    order.write({'opportunity_id': lead.id})

    activity_type_id = env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
    if activity_type_id:
        env['mail.activity'].sudo().create({
            'res_model_id': env['ir.model']._get_id('crm.lead'),
            'res_id': lead.id,
            'activity_type_id': activity_type_id.id,
            'summary': 'Seguimiento pedido desde WhatsApp',
            'note': f"Revisar el pedido {order.name} para contacto con el cliente.",
            'user_id': lead.user_id.id,
        })
    return order

def handle_crear_pedido(env, partner, text, memory):
    openai.api_key = env['ir.config_parameter'].sudo().get_param('openai.api_key')
    cart_items = json.loads(memory.pending_order_lines or '[]')
    context_info = "El usuario ya tiene productos en su carrito." if cart_items else "El carrito del usuario está vacío."
    system_prompt = prompts_config['create_order_system'].format(context_info=context_info)
    
    try:
        resp = openai.ChatCompletion.create(
            model=general_config['openai']['model'],
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": text}],
            functions=prompts_config['create_order_function'],
            function_call={"name": "lookup_product_variants"},
            temperature=0,
        )
        msg = resp.choices[0].message
    except Exception as e:
        _logger.error(f"❌ Error en la llamada a OpenAI: {e}")
        return messages_config['error_processing']

    if not msg.get('function_call'):
        _logger.warning("❌ GPT no devolvió una llamada a función.")
        return messages_config['error_default']

    args = json.loads(msg.function_call.arguments)
    products_to_add = args.get('products', [])
    if not products_to_add:
        return messages_config['product_not_found_gpt']

    first_product = products_to_add[0]
    query = first_product.get('query')
    qty = first_product.get('quantity')
    _logger.info(f"🔧 GPT detectó producto: {query} (Cantidad: {qty})")

    try:
        variants = lookup_product_variants(env, partner, query)
    except UserError as ue:
        _logger.warning(f"⚠️ Error buscando variantes: {str(ue)}")
        return str(ue)

    if len(variants) > 1:
        buttons = "\n".join([f"{i+1}) {v['name']} - ${v['price']:.2f}" for i, v in enumerate(variants)])
        memory.write({
            'flow_state': 'esperando_seleccion_producto',
            'data_buffer': json.dumps({'products': variants, 'qty': qty}),
        })
        return messages_config['ask_for_clarification'].format(query=query, buttons=buttons)

    variant = variants[0]
    pid, name, avail = variant['id'], variant['name'], int(variant['stock'])

    if not qty:
        memory.write({
            'flow_state': 'esperando_cantidad_producto',
            'last_variant_id': pid,
            'data_buffer': json.dumps({'product': variant}),
        })
        return messages_config['ask_for_quantity'].format(name=name)

    if qty <= avail:
        add_item_to_cart(memory, pid, qty)
        memory.write({'flow_state': 'esperando_confirmacion_pedido'})
        return messages_config['confirm_item_added'].format(qty=qty, name=name)
    else:
        memory.write({
            'flow_state': 'esperando_confirmacion_stock',
            'last_variant_id': pid,
            'last_qty_suggested': avail,
        })
        return messages_config['insufficient_stock'].format(avail=avail, name=name)