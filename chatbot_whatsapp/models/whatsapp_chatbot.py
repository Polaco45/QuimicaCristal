# -*- coding: utf-8 -*-
from odoo import models, api, _
import openai
import logging
import re
from os import environ

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  UTILIDADES
# ---------------------------------------------------------------------------
HTML_TAGS = re.compile(r"<[^>]+>")


def clean_html(text):
    """Quita etiquetas HTML y espacios sobrantes."""
    return re.sub(HTML_TAGS, "", text or "").strip()


def extract_user_data(text):
    """Detecta nombre y correo en el texto del usuario."""
    name_pat = r"(?:me llamo|soy|mi nombre es)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ]+)*)"
    email_pat = r"[\w\.\-]+@(?:gmail|hotmail|yahoo|outlook|icloud)\.(?:com|ar)"

    name = re.search(name_pat, text, re.I)
    email = re.search(email_pat, text)

    return {
        "name": name.group(1).strip() if name else None,
        "email": email.group(0) if email else None,
    }


def has_greeting(text):
    """¿El texto contiene un saludo clásico?"""
    return any(
        kw in text
        for kw in ("hola", "buenas", "buen día", "buenas tardes", "buenas noches", "qué tal")
    )


def has_product_kw(text):
    """¿El texto contiene palabras de producto/precio?"""
    kws = (
        "precio",
        "comprar",
        "producto",
        "catálogo",
        "cera",
        "detergente",
        "lavandina",
        "limpiador",
        "pisos",
    )
    return any(kw in text for kw in kws)


# ---------------------------------------------------------------------------
#  MODELO EXTENDIDO
# ---------------------------------------------------------------------------
class WhatsAppMessage(models.Model):
    _inherit = "whatsapp.message"

    # ---------------------------------------------------------------------
    #  CREACIÓN DE MENSAJE ENTRANTE
    # ---------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)

        for message in records:
            if (
                message.state == "received"
                and message.mobile_number
                and message.body
            ):
                plain_body = clean_html(message.body)
                _logger.info("Mensaje recibido (ID %s): %s", message.id, plain_body)

                # 1) Obtener respuesta
                response = message._generate_reply(plain_body)

                # 2) Garantizar cuerpo no vacío
                response_text = (response or "").strip()
                if not response_text:
                    response_text = _(
                        "Lo siento, no pude procesar tu consulta. "
                        "Visitá www.quimicacristal.com o escribinos nuevamente 😊."
                    )

                _logger.info("Mensaje a enviar: %s", response_text)

                # 3) Crear y enviar
                try:
                    out_msg = self.env["whatsapp.message"].sudo().create(
                        {
                            "mobile_number": message.mobile_number,
                            "body": response_text,
                            "state": "outgoing",
                            "create_uid": self.env.ref("base.user_admin").id,
                            "wa_account_id": (
                                message.wa_account_id.id if message.wa_account_id else False
                            ),
                        }
                    )
                    out_msg._send_message()
                except Exception as e:
                    _logger.error("Error enviando mensaje: %s", e)

                # 4) Guardar nombre/email en partner
                partner = self.env["res.partner"].sudo().search(
                    [("phone", "=", message.mobile_number)], limit=1
                )
                if partner:
                    data = extract_user_data(plain_body)
                    updates = {}
                    if data["name"] and not partner.name:
                        updates["name"] = data["name"]
                    if data["email"] and not partner.email:
                        updates["email"] = data["email"]
                    if updates:
                        _logger.info("Actualizando partner %s: %s", partner.id, updates)
                        partner.sudo().write(updates)

        return records

    # ---------------------------------------------------------------------
    #  GENERADOR DE RESPUESTA
    # ---------------------------------------------------------------------
    def _generate_reply(self, user_text):
        api_key = (
            self.env["ir.config_parameter"].sudo().get_param("openai.api_key")
            or environ.get("OPENAI_API_KEY")
        )
        if not api_key:
            _logger.error("OpenAI API‑Key no configurada.")
            return None
        openai.api_key = api_key

        lower = user_text.lower()

        # 1) Respuesta inmediata si pide productos/precios
        if has_product_kw(lower):
            return (
                "Tenemos muchos productos que pueden interesarte 😄.\n"
                "Consultá el catálogo y hacé tu pedido en 👉 www.quimicacristal.com\n\n"
                "📦 Envío gratis en compras desde $30.000.\n"
                "¡Aprovechá la promo del mes! 🎉"
            )

        # 2) Preparar contexto (últimos 3 mensajes)
        recent = self.env["whatsapp.message"].sudo().search(
            [
                ("mobile_number", "=", self.mobile_number),
                ("id", "<", self.id),
                ("body", "!=", False),
            ],
            order="id desc",
            limit=3,
        )
        history = [
            {
                "role": "user" if m.state == "received" else "assistant",
                "content": clean_html(m.body),
            }
            for m in reversed(recent)
        ]
        history.append({"role": "user", "content": user_text})

        # 3) ¿Ya saludamos? (buscar saludo en último mensaje del bot)
        last_bot = next(
            (m for m in recent if m.state == "outgoing"), None
        )
        already_greeted = last_bot and has_greeting(clean_html(last_bot.body).lower())

        # 4) Prompt del sistema
        system_msg = (
            "Eres el asistente virtual de Química Cristal. "
            "Tono: cálido, cercano, divertido y persuasivo.\n"
            "• Saluda SOLO si el usuario te saluda y todavía no lo has saludado.\n"
            "• Si no sabes algo, indica que visite www.quimicacristal.com "
            "o escriba al WhatsApp 3585481199.\n"
            "• Recordá el envío gratis desde $30.000 y las promos vigentes.\n"
            "• Pedí nombre y correo si aún no los tenés, de forma natural."
        )

        # 5) Ajustar temperatura y hacer llamada
        try:
            resp = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "system", "content": system_msg}] + history,
                temperature=0.5,
                max_tokens=200,
            )
            reply = resp.choices[0].message.content.strip()

            # 6) Quitar saludo si no corresponde
            if has_greeting(reply.lower()) and (not has_greeting(lower) or already_greeted):
                # eliminar primera línea de saludo
                reply = "\n".join(reply.splitlines()[1:]).strip()

            return reply
        except Exception as e:
            _logger.error("Error OpenAI: %s", e, exc_info=True)
            return _(
                "Ups, hubo un problema técnico 🙈. "
                "Podés visitar www.quimicacristal.com o escribir al WhatsApp 3585481199."
            )
