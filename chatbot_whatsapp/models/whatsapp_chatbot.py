from odoo import models, api, _
import logging
import re

_logger = logging.getLogger(__name__)

REGALO_KEYWORDS = ['quiero mi regalo', 'regalo', '🎁']
RESPUESTA_INICIAL = (
    "🎉 ¡Felicitaciones! Ganaste hasta $10.000 en productos de limpieza.\n"
    "¿Querés usar tu regalo en la Tienda Web 🛒 o en el Local Físico 🏪?\n"
    "Respondé con 'Web', 'Tienda', 'Online' o 'Local', 'Negocio', etc."
)
RESPUESTA_CUPON = (
    "Tenés 3 días para usarlo. Si se te complica, avisanos 😉"
)

def contiene_palabra_clave(texto, palabras_clave):
    return any(palabra.lower() in texto.lower() for palabra in palabras_clave)

class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    @api.model_create_multi
    def create(self, vals_list):
        records = super(WhatsAppMessage, self).create(vals_list)
        for message in records:
            if message.state != 'received' or not message.mobile_number:
                continue

            texto = (message.body or "").strip().lower()
            if contiene_palabra_clave(texto, REGALO_KEYWORDS):
                respuesta = RESPUESTA_INICIAL
            elif contiene_palabra_clave(texto, ['web', 'tienda', 'online', 'comprar']):
                self._enviar_cupon(message)
                continue
            elif contiene_palabra_clave(texto, ['local', 'negocio', 'físico', 'fisico']):
                self._enviar_cupon(message)
                continue
            else:
                continue  # Ignora todos los demás mensajes

            self._crear_mensaje_salida(message, respuesta)

        return records

    def _crear_mensaje_salida(self, mensaje_entrada, texto):
        vals = {
            'mobile_number': mensaje_entrada.mobile_number,
            'body': texto,
            'state': 'outgoing',
            'create_uid': self.env.ref('base.user_admin').id,
            'wa_account_id': mensaje_entrada.wa_account_id.id if mensaje_entrada.wa_account_id else False,
        }
        mensaje_saliente = self.env['whatsapp.message'].sudo().create(vals)
        if hasattr(mensaje_saliente, '_send_message'):
            mensaje_saliente._send_message()

    def _enviar_cupon(self, mensaje_entrada):
        adjunto = self.env['ir.attachment'].sudo().search([('name', '=', 'cupon_web')], limit=1)
        if not adjunto:
            _logger.warning("Imagen de cupón no encontrada.")
            return

        mensaje_con_imagen = {
            'mobile_number': mensaje_entrada.mobile_number,
            'body': RESPUESTA_CUPON,
            'attachment_ids': [(6, 0, [adjunto.id])],
            'state': 'outgoing',
            'create_uid': self.env.ref('base.user_admin').id,
            'wa_account_id': mensaje_entrada.wa_account_id.id if mensaje_entrada.wa_account_id else False,
        }
        mensaje = self.env['whatsapp.message'].sudo().create(mensaje_con_imagen)
        if hasattr(mensaje, '_send_message'):
            mensaje._send_message()
