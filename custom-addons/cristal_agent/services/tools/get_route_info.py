# -*- coding: utf-8 -*-
"""
Tool: get_route_info

Devuelve la información REAL de la ruta del camión para un cliente o una ciudad:
si es Río Cuarto / circuito / fuera de zona, la próxima salida (registro en
preventa), el cierre de preventa, el mínimo, el flete, el umbral de envío gratis
(efectivo: rescate baja a $75.000) y una frase sugerida.

El bot NUNCA promete una fecha que no salga de esta tool.
"""
import logging

import pytz

from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)

WEEKDAYS_ES = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']


def _fmt_money(value):
    return '${:,.0f}'.format(value or 0).replace(',', '.')


@ToolRegistry.register
class GetRouteInfo(AgentTool):
    name = "get_route_info"
    description = (
        "Info REAL de la ruta del camión mayorista (sale los miércoles a pueblos de la "
        "zona) para un cliente (partner_id) o una ciudad (city). Devuelve: si es Río "
        "Cuarto, un circuito de la ruta o fuera de zona; la PRÓXIMA SALIDA (fecha del "
        "miércoles) y el CIERRE DE PREVENTA (lunes 18 h); el pedido mínimo, el flete y "
        "desde cuánto el envío es gratis; y una frase sugerida para el cliente. "
        "Llamala SIEMPRE antes de hablar de fechas/envío con un cliente de pueblo. "
        "NUNCA prometas una fecha que no salga de acá."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del cliente."},
            "city": {"type": "string",
                     "description": "Ciudad/localidad (si no tenés partner_id o querés "
                                    "consultar otra localidad)."},
        },
    }

    def _execute(self, env, run=None, partner_id=None, city=None, **kwargs):
        config = env['cristal.agent.config'].sudo().get_active()
        Circuit = env['cristal.agent.circuit'].sudo()

        partner = None
        if partner_id:
            partner = env['res.partner'].sudo().browse(int(partner_id))
            if not partner.exists():
                return {"error": f"partner_id={partner_id} no existe"}
        city_text = city or (partner.city if partner else None)

        # Circuito: el del partner (etiqueta/manual) manda; si no, por ciudad.
        circuit = partner.truck_circuit_id if partner and partner.truck_circuit_id else None
        info = Circuit.classify_city(city_text) if city_text else {'kind': 'empty'}
        if not circuit and info.get('kind') == 'circuit':
            circuit = info['circuit']

        if not circuit and info.get('kind') == 'empty':
            return {
                "ok": True, "zone": "unknown", "needs_city": True,
                "message_for_bot": (
                    "No sé la localidad del cliente. PREGUNTALA antes de cotizar o de "
                    "hablar de envío (ej: '¿De qué localidad es su comercio?'). Cuando te "
                    "la diga, guardala con update_partner(city=...)."),
            }

        if not circuit and info.get('kind') == 'rio_cuarto':
            no_day = WEEKDAYS_ES[int(config.rc_no_delivery_weekday) % 7] if config \
                else 'miércoles'
            return {
                "ok": True, "zone": "rio_cuarto", "city": info['canonical'],
                "no_delivery_weekday": no_day,
                "message_for_bot": (
                    f"{info['canonical']} es reparto normal de Río Cuarto: entregamos SOLO "
                    f"por la mañana y NO hay reparto los {no_day.upper()} (ese día sale el "
                    f"camión de la ruta). No ofrezcas ENTREGA ese día. El RETIRO en planta "
                    f"ese día SÍ se puede, en el horario oficial de la planta. NUNCA "
                    f"comprometas un día ni un horario de entrega: decí 'le confirmamos el "
                    f"día de entrega' y escalá el pedido a Joaco."),
                "suggested_phrase": "Le confirmamos el día de entrega apenas lo programemos.",
            }

        if not circuit and info.get('kind') == 'maybe':
            # v1.36: localidad parecida a una de la ruta pero no exacta ("Olver" →
            # Holmberg). Se PREGUNTA; nunca se marca fuera de zona por un error de tipeo.
            cand = info['candidate']
            return {
                "ok": True, "zone": "unknown", "needs_confirmation": True,
                "candidate_city": cand,
                "suggested_phrase": f"¿Se refiere a {cand}?",
                "message_for_bot": (
                    f"'{city_text}' no coincide exacto con ninguna localidad, pero se parece "
                    f"a {cand} (ruta del camión). PREGUNTALE: '¿Se refiere a {cand}?'. Si "
                    f"dice que sí, guardala con update_partner(city='{cand}'). NO lo marques "
                    f"fuera de zona ni hables de envío hasta confirmarlo."),
            }

        if not circuit:
            return {
                "ok": True, "zone": "fuera_zona", "city": info.get('canonical') or city_text,
                "escalate": True,
                "suggested_phrase": (
                    "A su localidad no llega nuestro reparto. Puede retirar el pedido en "
                    "nuestra planta (San Martín 2350, Río Cuarto) o enviarlo con el "
                    "transporte que usted elija, a su cargo."),
                "message_for_bot": (
                    f"{info.get('canonical') or city_text} está FUERA de los 4 circuitos de "
                    f"la ruta. NO ofrezcas condiciones de envío (ni mínimo de ruta, ni "
                    f"flete, ni fecha) y NUNCA digas que Joaquín le coordina el envío. "
                    f"Ofrecé las dos opciones de `suggested_phrase` (retiro en planta o "
                    f"transporte a cargo del cliente). Pasale la lista, tratalo de USTED y "
                    f"escalá a Joaco UNA vez con escalate_to_joaco."),
            }

        # ── Es de un circuito: próxima salida real (registro en preventa) ──
        departure = circuit.get_next_departure()
        if not config:
            return {"ok": False, "escalate": True,
                    "message_for_bot": "No hay configuración activa de la ruta: no "
                                       "prometas condiciones; escalá a Joaco."}
        # v1.37: nada fijo en el código: mínimo, flete y envío sin cargo salen de la
        # configuración (route_*). La base del envío sin cargo son todas las líneas
        # sin IVA de los productos, sin flete ni bidones (como el mínimo): ver sale.order.
        min_order = config.route_min_order
        freight = config.route_freight_amount
        free_from = config.route_free_shipping_from
        town = info.get('canonical') if info.get('kind') == 'circuit' else (city_text or '')

        if not departure:
            return {
                "ok": True, "zone": "ruta_camion", "circuit": circuit.name, "city": town,
                "departure": None, "escalate": True,
                "message_for_bot": (
                    f"{town} es del circuito {circuit.name}, pero NO hay una salida "
                    f"programada. NO inventes fecha: escalá a Joaco."),
            }

        rescate = departure.state == 'rescate'
        effective_free_from = departure.rescue_free_shipping_from if rescate else free_from

        tzname = (config.timezone if config and config.timezone
                  else 'America/Argentina/Cordoba')
        tz = pytz.timezone(tzname)
        cutoff_local = pytz.utc.localize(departure.get_preventa_cutoff()).astimezone(tz)
        dep_date = departure.date
        dep_txt = f"{WEEKDAYS_ES[dep_date.weekday()]} {dep_date.strftime('%d/%m')}"
        cutoff_txt = (f"{WEEKDAYS_ES[cutoff_local.weekday()]} "
                      f"{cutoff_local.strftime('%d/%m')} a las {cutoff_local.strftime('%H')} h")

        phrase = (
            f"Pasamos por {town} el {dep_txt}; tomamos pedidos hasta el {cutoff_txt}. "
            f"Pedido mínimo {_fmt_money(min_order)} en productos. Flete {_fmt_money(freight)}, "
            f"sin cargo desde {_fmt_money(effective_free_from)}.")
        courtesy = None
        if rescate and departure.courtesy_product_id:
            courtesy = departure.courtesy_product_id.display_name
            phrase += f" Y le sumamos de cortesía: {courtesy}."

        # v1.36: si la salida cae en un día cerrado (feriado), no se promete.
        from ..helpers import closed_day_reason
        dep_closed = closed_day_reason(env, dep_date)
        if dep_closed:
            return {
                "ok": True, "zone": "ruta_camion", "circuit": circuit.name, "city": town,
                "departure_id": departure.id, "departure_on_closed_day": dep_closed,
                "escalate": True,
                "message_for_bot": (
                    f"La próxima salida de {circuit.name} cae el {dep_txt}, que es "
                    f"{dep_closed}. NO prometas esa fecha ni otra: decile que le confirmamos "
                    f"la fecha de paso y escalá a Joaco para que reprograme la salida."),
            }

        return {
            "ok": True,
            "zone": "ruta_camion",
            "circuit": circuit.name,
            "city": town,
            "departure_id": departure.id,
            "departure_date": dep_date.isoformat(),
            "departure_text": dep_txt,
            "departure_state": departure.state,
            "preventa_cutoff_local": cutoff_local.strftime('%Y-%m-%d %H:%M'),
            "preventa_cutoff_text": cutoff_txt,
            "min_order": min_order,
            "freight_amount": freight,
            "free_shipping_from": effective_free_from,
            "rescate": rescate,
            "courtesy_product": courtesy,
            "suggested_phrase": phrase,
            "message_for_bot": (
                "Usá ESTA fecha y ESTE cierre (no inventes otros). El MÍNIMO se mide sobre "
                "los productos sin IVA (sin flete ni bidones), y el ENVÍO SIN CARGO también. "
                "NUNCA menciones el "
                "IVA. Es cliente de "
                "pueblo: si es nuevo, tratalo de USTED (le / su / ¿cómo está?), nunca de "
                "vos, salvo que él te tutee. "
                + ("Salida en RESCATE: envío gratis desde $75.000 y ofrecé el producto de "
                   "cortesía. " if rescate else "")),
        }
