from odoo import models, api, _
import openai
import logging

_logger = logging.getLogger(__name__)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super(WhatsAppMessage, self).create(vals_list)
        for message in records:
            if message.state == 'received' and message.mobile_number and message.body:
                _logger.info("Mensaje recibido (ID %s): body = %s", message.id, message.body)
                
                chatbot_response = message._get_chatbot_response(message.body)
                _logger.info("Respuesta cruda del chatbot para mensaje %s: %s", message.id, chatbot_response)

                response_text = chatbot_response.strip() if chatbot_response and chatbot_response.strip() else _("Lo siento, no pude procesar tu consulta.")
                if not chatbot_response or not chatbot_response.strip():
                    _logger.warning("La respuesta del chatbot quedó vacía para el mensaje %s", message.id)
                try:
                    outgoing_vals = {
                        'mobile_number': message.mobile_number,
                        'body': response_text,
                        'state': 'outgoing',
                        'create_uid': self.env.ref('base.user_admin').id,
                        'wa_account_id': message.wa_account_id.id if message.wa_account_id else False,
                    }
                    outgoing_msg = self.env['whatsapp.message'].sudo().create(outgoing_vals)
                    outgoing_msg.sudo().write({'body': response_text})
                    _logger.info("Mensaje saliente creado: ID %s, body = %s", outgoing_msg.id, outgoing_msg.body)
                    
                    if hasattr(outgoing_msg, '_send_message'):
                        outgoing_msg._send_message()
                    else:
                        _logger.info("No se encontró _send_message; el mensaje quedará en cola.")
                except Exception as e:
                    _logger.error("Error al crear/enviar el mensaje saliente para el registro %s: %s", message.id, e)
        return records

    def _get_chatbot_response(self, user_message):
        """
        Responde al mensaje del cliente de dos maneras:
          1. Si el mensaje contiene palabras clave (como 'comprar', 'producto', etc.), se busca en el catálogo de 
             productos publicados (is_published=True) y se devuelve un listado (máximo 10) con enlaces al sitio web.
          2. Si no se detectan esas palabras, se arma el contexto de la conversación (últimos 5 mensajes) y se consulta
             a OpenAI utilizando un prompt base que indica un tono cálido, humano y personal (preguntando, por ejemplo, 
             el nombre del cliente si es la primera interacción).
        """
        # --- Sección 1: Búsqueda de Productos  
        product_keywords = ['comprar', 'producto', 'venden', 'tienen', 'oferta', 'catálogo', 'consulta']
        if any(kw in user_message.lower() for kw in product_keywords):
            Product = self.env['product.template']
            palabras = user_message.lower().split()
            
            dominio = [('is_published', '=', True)]
            condiciones = []
            for palabra in palabras:
                condiciones += [
                    ('name', 'ilike', palabra),
                    ('description', 'ilike', palabra),
                    ('description_sale', 'ilike', palabra),
                ]
            if condiciones:
                if len(condiciones) > 1:
                    dominio += ['|'] * (len(condiciones) - 1)
                dominio += condiciones

            productos = Product.search(dominio)
            if productos:
                max_mostrar = 10
                total_encontrados = len(productos)
                mostrados = productos[:max_mostrar]
                links = [f"🔹 {p.name}: https://quimicacristal.com{p.website_url}" for p in mostrados if p.website_url]
                mensaje = "¡Sí! Encontré estos productos relacionados:\n" + "\n".join(links)
                if total_encontrados > max_mostrar:
                    mensaje += (
                        f"\n\n(Se encontraron {total_encontrados} resultados, te muestro los primeros {max_mostrar}. "
                        "Podés visitar nuestro sitio para ver más.)"
                    )
                return mensaje

        # --- Sección 2: Construcción de contexto conversacional  
        recent_messages = self.env['whatsapp.message'].sudo().search([
            ('mobile_number', '=', self.mobile_number),
            ('id', '<', self.id),
            ('body', '!=', False),
        ], order='id desc', limit=5)
        context_messages = []
        for msg in reversed(recent_messages):
            role = 'user' if msg.state == 'received' else 'assistant'
            context_messages.append({
                "role": role,
                "content": msg.body
            })
        context_messages.append({"role": "user", "content": user_message})
        
        # --- Sección 3: Prompt base (System Message) personalizado
        system_message = (
            "Sos un asistente de atención al cliente de Química Cristal, una empresa especializada en productos de limpieza para el hogar e instituciones. "
            "Tu tono debe ser cálido, humano y cercano. "
            "Cuando recibas un saludo de un cliente y sea la primera interacción, saluda y preguntale su nombre, por ejemplo: "
            "'¡Hola! Gracias por comunicarte con Química Cristal. ¿Cómo te llamás?'. "
            "Si se hacen consultas sobre productos, proporcioná enlaces directos a nuestro sitio web sin mencionar precios. "
            "Mantené una comunicación empática y personalizada."
        )
        messages = [{"role": "system", "content": system_message}] + context_messages

        # --- Sección 4: Consulta a OpenAI  
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.4,
                max_tokens=150,
            )
            _logger.info("Respuesta completa de OpenAI para el mensaje '%s': %s", user_message, response)
            try:
                return response.choices[0].message.content.strip()
            except Exception:
                return response.choices[0].message['content'].strip()
        except Exception as e:
            _logger.error("Error al obtener respuesta de OpenAI: %s", e, exc_info=True)
            return _("Lo siento, hubo un problema técnico al generar la respuesta.")
