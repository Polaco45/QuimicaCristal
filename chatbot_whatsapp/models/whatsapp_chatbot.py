def _get_chatbot_response(self, user_message):
    """
    Llama a la API de OpenAI para obtener una respuesta basada en el mensaje del usuario,
    inyectando información actualizada de productos (precios, stock) en el prompt.
    En caso de error, se intenta buscar un producto en el catálogo y se devuelve su enlace.
    """
    try:
        api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
        if not api_key:
            _logger.error("La API key de OpenAI no está configurada en ir.config_parameter")
            return _("Lo siento, no pude procesar tu mensaje.")
        openai.api_key = api_key

        # Se arma el prompt con contexto (como en el ejemplo anterior)
        pricelist = self.env.user.partner_id.property_product_pricelist
        product_records = self.env['product.template'].sudo().search([], limit=5)
        product_info = "Información actual de productos: "
        if product_records:
            for prod in product_records:
                try:
                    price_actual = prod.get_display_price(pricelist)
                except Exception:
                    price_actual = prod.with_context(pricelist=pricelist.id).price
                product_info += f"{prod.name} (Precio: ${price_actual}, Stock: {prod.qty_available}); "
        else:
            product_info += "No hay datos de productos disponibles. "

        system_message = {
            "role": "system",
            "content": (
                "Eres un asistente virtual para Química Cristal. Responde de forma natural, cercana y humana. "
                "Ayuda a los clientes a cargar pedidos y consulta precios. " + product_info
            )
        }
        messages = [
            system_message,
            {"role": "user", "content": user_message}
        ]
        response = openai.ChatCompletion.create(
            model='gpt-3.5-turbo',
            messages=messages
        )
        _logger.info("Respuesta completa de OpenAI para el mensaje '%s': %s", user_message, response)
        try:
            answer = response.choices[0].message.content.strip()
        except Exception:
            answer = response.choices[0].message['content'].strip()
        return answer

    except Exception as e:
        _logger.error("Error al obtener respuesta de OpenAI: %s", e, exc_info=True)
        # Fallback: Buscar un producto que coincida con el mensaje del usuario.
        product = self.env['product.template'].sudo().search([('name', 'ilike', user_message)], limit=1)
        if product:
            # Si el producto tiene un campo website_url o se puede construir el enlace
            website_url = product.website_url or f"https://tu-sitio.com/shop/product/{product.id}"
            return _("No pude generar la respuesta, pero te recomiendo revisar este producto: ") + website_url
        else:
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
