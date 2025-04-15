@staticmethod
def get_product_price(env, product_name):
    product = env['product.product'].search(
        ['|', ('name', 'ilike', product_name),
              ('default_code', '=', product_name)],
        limit=1)
    if not product:
        return {"found": False,
                "message": f"No encontré {product_name} en el catálogo."}

    # ► NUEVO
    pricelist = env['product.pricelist'].search([], limit=1)
    if pricelist:
        price = product.with_context(pricelist=pricelist.id).price
    else:
        price = product.standard_price
    # ▲ NUEVO

    stock = product.qty_available
    return {"found": True,
            "name": product.display_name,
            "price": price,
            "stock": stock}
