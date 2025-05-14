@api.model_create_multi
def create(self, vals_list):
    records = super(WhatsAppMessage, self).create(vals_list)
    for message in records:
        plain_body = clean_html(message.body or "")
        lower_msg = plain_body.lower()

        if message.state == 'received' and message.mobile_number and plain_body:
            _logger.info("Mensaje recibido (ID %s): %s", message.id, plain_body)

            # Normalizamos teléfono
            normalized_phone = normalize_phone(message.mobile_number)

            # Buscamos el contacto
            partner = self.env['res.partner'].sudo().search([
                '|',
                ('phone', 'ilike', normalized_phone),
                ('mobile', 'ilike', normalized_phone)
            ], limit=1)

            # --- FLUJO: QUIERO MI REGALO ---
            if "quiero mi regalo" in lower_msg and "🎁" in lower_msg:
                try:
                    self.env['whatsapp.message'].sudo().create({
                        'mobile_number': message.mobile_number,
                        'template_id': 188,  # ID de tu plantilla 'promo_regalo_10000'
                        'state': 'outgoing',
                    })
                    _logger.info("Plantilla de regalo enviada correctamente.")
                except Exception as e:
                    _logger.error("Error al enviar plantilla de regalo: %s", e)
                continue

            # --- FLUJO: CLIC EN BOTÓN ---
            if lower_msg in ["tienda web", "local físico"]:
                try:
                    attachment = self.env['ir.attachment'].sudo().search([
                        ('name', '=', 'cupon_web'),
                        ('public', '=', True)
                    ], limit=1)

                    if attachment:
                        file_url = f"/web/content/{attachment.id}?download=true"
                        image_tag = f'<img src="{file_url}" alt="Cupón Web" />'
                        response_text = "Tenés 3 días para usarlo, no te duermas. 🕒"
                        self.env['whatsapp.message'].sudo().create({
                            'mobile_number': message.mobile_number,
                            'body': response_text + "\n" + file_url,
                            'state': 'outgoing',
                        })
                        _logger.info("Imagen de cupón enviada con éxito.")
                    else:
                        _logger.warning("No se encontró el archivo público 'cupon_web'.")
                except Exception as e:
                    _logger.error("Error al enviar el cupón: %s", e)
                continue

            # --- RESPUESTA GENÉRICA ---
            self.env['whatsapp.message'].sudo().create({
                'mobile_number': message.mobile_number,
                'body': "Gracias por escribirnos 😊 ¿Querés conocer nuestras ofertas? Visitá www.quimicacristal.com",
                'state': 'outgoing',
            })

    return records
