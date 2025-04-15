import logging
import requests

from odoo import models, api

_logger = logging.getLogger(__name__)

class WhatsappMessage(models.Model):
    _inherit = 'whatsapp.message'
    
    @api.model
    def create(self, vals):
        """
        Sobrescribe el método create para responder automáticamente a mensajes de WhatsApp entrantes.
        Si se crea un nuevo mensaje (o varios) con estado 'received', se genera una respuesta usando la API de OpenAI (modelo GPT-3.5-turbo)
        y se crea un mensaje saliente correspondiente para cada uno.
        """
        # Crear el/los nuevo(s) registro(s) usando la función create original
        records = super(WhatsappMessage, self).create(vals)
        # Si se crean múltiples registros a la vez, iterar por cada uno
        for record in records:
            if record.state == 'received':
                # Procesar solo mensajes entrantes (estado 'received')
                try:
                    # Validar que el mensaje entrante tenga contenido de texto
                    message_text = (record.body or "").strip()
                    if not message_text:
                        _logger.info("Mensaje entrante %s sin contenido; se omite la respuesta automática.", record.id)
                        continue  # Saltar a siguiente si no hay texto
                    # Verificar que la API key de OpenAI esté configurada
                    api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key')
                    if not api_key:
                        _logger.error("API key de OpenAI no configurada; no se puede responder al mensaje %s.", record.id)
                        continue
                    # Preparar la solicitud a la API de OpenAI
                    openai_endpoint = "https://api.openai.com/v1/chat/completions"
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    }
                    payload = {
                        "model": "gpt-3.5-turbo",
                        "messages": [
                            {"role": "system", "content": "Eres un asistente virtual útil."},
                            {"role": "user", "content": message_text}
                        ],
                        # Limitar los tokens de respuesta para evitar respuestas muy largas
                        "max_tokens": 500,
                        "n": 1,
                        "temperature": 0.5,
                    }
                    response = requests.post(openai_endpoint, json=payload, headers=headers, timeout=10)
                    if response.status_code != 200:
                        _logger.error("Falló la llamada a OpenAI API para mensaje %s. Código: %s, Respuesta: %s",
                                      record.id, response.status_code, response.text)
                        continue
                    data = response.json()
                    # Extraer el texto generado de la respuesta de la API
                    generated_text = ""
                    try:
                        generated_text = data.get("choices")[0].get("message").get("content", "").strip()
                    except Exception as parse_err:
                        _logger.error("Respuesta de OpenAI no tiene el formato esperado para mensaje %s: %s",
                                      record.id, str(parse_err))
                    if not generated_text:
                        _logger.warning("La API de OpenAI no generó contenido para el mensaje %s; no se enviará respuesta.", record.id)
                        continue
                    # Preparar valores para el registro del mensaje saliente
                    outgoing_vals = {
                        'mobile_number': record.mobile_number,
                        'body': generated_text,
                        'state': 'outgoing',
                        'wa_account_id': record.wa_account_id.id if record.wa_account_id else False,
                    }
                    try:
                        # Crear el mensaje saliente como el usuario Sergio Ramello (ID interno 2)
                        outgoing_msg = self.env['whatsapp.message'].sudo(2).create(outgoing_vals)
                        _logger.info("Mensaje de respuesta %s creado (en respuesta al mensaje %s).", outgoing_msg.id, record.id)
                    except Exception as create_err:
                        _logger.error("No se pudo crear el mensaje de salida para %s: %s", record.id, str(create_err))
                except Exception as e:
                    _logger.exception("Error procesando respuesta automática para mensaje %s: %s", record.id, str(e))
        return records
