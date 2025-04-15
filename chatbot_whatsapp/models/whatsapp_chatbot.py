from odoo import models, api, _
import openai
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        # Se crean uno o varios mensajes
        records = super(WhatsAppMessage, self).create(vals_list)
        for message in records:
            # Procesamos sólo mensajes recibidos con state 'received' y con número y cuerpo definidos
            if message.state == 'received' and message.mobile_number and message.body:
                _logger.info("Mensaje recibido (ID %s): body = %s", message.id, message.body)
                chatbot_response = message._get_chatbot_response(message.body)
                _logger.info("Respuesta cruda del chatbot para mensaje %s: %s", message.id, chatbot_response)
                # Usamos la respuesta si no es vacía; de lo contrario, asignamos un mensaje predeterminado
                if chatbot_response and chatbot_response.strip():
                    response_text = chatbot_response.strip()
                else:
                    response_text = _("Lo siento, no pude procesar tu consulta.")
                    _logger.warning("La respuesta del chatbot quedó vacía para el mensaje %s", message.id)
                try:
                    outgoing_vals = {
                        'mobile_number': message.mobile_number,   # Responder al mismo número
                        'body': response_text,                      # Valor inicial, que luego se fuerza a guardar
                        'state': 'outgoing',                        # Se asume que 'outgoing' indica mensaje en cola para enviar
                        'create_uid': self.env.ref('base.user_admin').id,  # Asigna el usuario (modificar si es distinto)
                        'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
                    }
                    # Crear el mensaje saliente con sudo (para evitar restricciones)
                    outgoing_msg = self.env['whatsapp.message'].sudo().create(outgoing_vals)
                    # Forzar que el contenido se guarde en 'body'
                    outgoing_msg.sudo().write({'body': response_text})
                    _logger.info("Mensaje saliente creado: ID %s, body = %s", outgoing_msg.id, outgoing_msg.body)
                    # Si existe método para enviar el mensaje inmediatamente, lo llamamos; de lo contrario, queda en cola.
                    if hasattr(outgoing_msg, '_send_message'):
                        outgoing_msg._send_message()
                    else:
                        _logger.info("No se encontró _send_message; el mensaje quedará en cola.")
                except Exception as e:
                    _logger.error("Error al crear/enviar el mensaje saliente para el registro %s: %s", message.id, e)
        return records

    def _get_chatbot_response(self, user_message):
        """
        Llama a la API de OpenAI para obtener una respuesta basada en el mensaje del usuario,
        inyectando información actualizada de productos (precios, stock) en el prompt.
        """
        try:
            api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
            if not api_key:
                _logger.error("La API key de OpenAI no está configurada en ir.config_parameter")
                return _("Lo siento, no pude procesar tu mensaje.")
            openai.api_key = api_key

            # Obtener información dinámica de productos:
            # Se utiliza la lista de precios del partner del usuario actual para calcular el precio
            pricelist = self.env.user.partner_id.property_product_pricelist
            product_records = self.env['product.template'].sudo().search([], limit=5)
            product_info = "Información actual de productos: "
            if product_records:
                for prod in product_records:
                    try:
                        # Se intenta obtener el precio computado usando el método get_display_price.
                        price_actual = prod.get_display_price(pricelist)
                    except Exception:
                        # En caso de fallo, se usa el precio base con el contexto de la lista de precios.
                        price_actual = prod.with_context(pricelist=pricelist.id).price
                    product_info += f"{prod.name} (Precio: ${price_actual}, Stock: {prod.qty_available}); "
            else:
                product_info += "No hay datos de productos disponibles. "

            # Construir el mensaje del sistema inyectando el contexto
            system_message = {
                "role": "system",
                "content": (
                    "Eres un asistente virtual para Química Cristal. Responde de forma natural, cercana y humana. "
                    "Ayuda a los clientes a cargar pedidos y consulta precios. " + product_info
                )
            }

            # Armar el prompt completo con el mensaje del sistema y el mensaje del usuario
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
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
