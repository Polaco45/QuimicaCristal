# -*- coding: utf-8 -*-
"""
Tool: register_referral (v1.56)

"Vengo de parte de X" / "me lo recomendó X": se registra quién lo recomendó y se le deja
al nuevo cliente un crédito por referido (config.referral_discount, 5 %) para su primer
pedido. Cuando ese primer pedido se confirma, quien lo recomendó recibe el mismo crédito
para su próximo pedido y Claudio le avisa (models/sale_order.py). El 20 % de primera
compra de Río Cuarto tiene prioridad: no se acumulan.
"""
import logging
import re

from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class RegisterReferral(AgentTool):
    name = "register_referral"
    description = (
        "Registrá que un cliente vino RECOMENDADO por otro ('vengo de parte de Marta', 'me "
        "pasó el contacto Juan de la despensa'). Buscá a quien lo recomendó por nombre o "
        "teléfono (o pasá referrer_partner_id si lo tenés). Deja el crédito por referido al "
        "nuevo cliente para su primer pedido (si no le corresponde el 20% de Río Cuarto) y, "
        "cuando ese pedido se confirme, el sistema le da el crédito a quien lo recomendó y te "
        "agenda avisarle. Devuelve a quién encontró; si hay varios candidatos, preguntale al "
        "cliente cuál es antes de registrar."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {"type": "integer", "description": "ID del cliente nuevo (el referido)."},
            "referrer_name": {"type": "string", "description": "Nombre de quien lo recomendó, como lo dijo."},
            "referrer_phone": {"type": "string", "description": "Teléfono de quien lo recomendó, si lo dio."},
            "referrer_partner_id": {"type": "integer", "description": "ID exacto de quien lo recomendó, si ya lo sabés."},
        },
        "required": ["partner_id"],
    }

    def _execute(self, env, run=None, partner_id=None, referrer_name=None, referrer_phone=None,
                 referrer_partner_id=None, **kwargs):
        Partner = env['res.partner'].sudo()
        partner = Partner.browse(int(partner_id or 0)).exists()
        if not partner:
            return {"error": "partner_id no existe"}
        config = env['cristal.agent.config'].sudo().get_active()
        pct = float(config.referral_discount or 5.0) if config else 5.0

        referrer = Partner
        if referrer_partner_id:
            referrer = Partner.browse(int(referrer_partner_id)).exists()
        elif referrer_phone:
            digits = re.sub(r'\D', '', referrer_phone)[-8:]
            if len(digits) >= 7:
                referrer = Partner.search(['|', ('mobile', 'ilike', digits), ('phone', 'ilike', digits),
                                           ('id', '!=', partner.id)], limit=5)
        if not referrer and referrer_name:
            words = [w for w in referrer_name.split() if len(w) > 2]
            dom = [('id', '!=', partner.id)]
            for w in words:
                dom.append(('name', 'ilike', w))
            cands = Partner.search(dom, limit=10)
            with_sales = cands.filtered(lambda p: env['sale.order'].sudo().search_count(
                [('partner_id', '=', p.id), ('state', 'in', ('sale', 'done'))]))
            referrer = with_sales or cands
        if not referrer:
            return {"ok": False, "not_found": True,
                    "message_for_bot": "No encontré a quien lo recomendó. Preguntale el nombre "
                                       "completo o el teléfono de esa persona y volvé a llamar."}
        if len(referrer) > 1:
            return {"ok": False, "ambiguous": True,
                    "candidates": [{"partner_id": p.id, "name": p.name, "city": p.city or ''}
                                   for p in referrer],
                    "message_for_bot": "Hay varios clientes con ese nombre: preguntale cuál es "
                                       "(localidad o comercio) y volvé a llamar con referrer_partner_id."}
        if referrer.id == partner.id:
            return {"error": "el referido y quien lo recomendó son el mismo contacto"}
        partner.write({'agent_referred_by_id': referrer.id})
        partner.agent_grant_referral_credit(pct, f"recomendado por {referrer.name}")
        referrer.append_agent_observation(f"Recomendó a {partner.name} ({partner.city or 'sin localidad'}).")
        return {
            "ok": True, "referrer": {"partner_id": referrer.id, "name": referrer.name},
            "credit_percent": pct,
            "message_for_bot": (
                f"Registrado: {partner.name} vino recomendado por {referrer.name}. Decile que su "
                f"primer pedido lleva {pct:g}% por venir recomendado (create_sale_order lo aplica "
                f"solo; si es de Río Cuarto / Las Higueras le corresponde el 20% de primera "
                f"compra, que es mejor y no se acumula). A quien lo recomendó se le avisa solo "
                f"cuando este pedido se confirme."),
        }
