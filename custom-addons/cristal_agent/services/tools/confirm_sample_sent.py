# -*- coding: utf-8 -*-
"""
Tool: confirm_sample_sent

Registra que se confirmó el envío de muestra a un cliente.
- Setea agent_sample_sent_at = now en el lead
- Calcula agent_sample_expected_delivery (lun-jue: +1 día hábil, vie-dom: lunes)
- Agenda automáticamente un chequeo a +2 días post-entrega
- Mueve la fase a phase_2 si está en phase_1
"""
import logging
from datetime import date, timedelta
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


def _next_business_delivery(today=None):
    """Devuelve el próximo día de entrega:
    - lun-jue → mañana
    - vie-dom → lunes próximo
    """
    if today is None:
        today = date.today()
    weekday = today.weekday()  # 0=lun, 4=vie, 5=sáb, 6=dom
    if weekday <= 3:  # lun-jue
        return today + timedelta(days=1)
    if weekday == 4:  # vie
        return today + timedelta(days=3)  # lunes
    if weekday == 5:  # sáb
        return today + timedelta(days=2)
    return today + timedelta(days=1)  # dom → lunes


@ToolRegistry.register
class ConfirmSampleSent(AgentTool):
    name = "confirm_sample_sent"
    description = (
        "Registra que se coordinó/confirmó el envío de la muestra al cliente. "
        "Setea fecha de envío, calcula entrega prevista (lun-jue: +1 día hábil; "
        "vie-dom: lunes), agenda chequeo automático a +2 días post-entrega, "
        "y mueve la fase del lead a phase_2 si estaba en phase_1. "
        "Llamala SIEMPRE que confirmes una muestra con el cliente."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "lead_id": {
                "type": "integer",
                "description": "ID del crm.lead. Si no lo tenés, "
                               "primero buscalo con search_partners o read_partner.",
            },
            "products_sample": {
                "type": "string",
                "description": "(Opcional) Resumen de qué productos van en la muestra "
                               "(para guardar en el lead).",
            },
        },
        "required": ["lead_id"],
    }

    def _execute(self, env, run=None, lead_id=None, products_sample=None, **kwargs):
        if not lead_id:
            return {"error": "lead_id es obligatorio"}

        Lead = env['crm.lead'].sudo()
        lead = Lead.browse(int(lead_id))
        if not lead.exists():
            return {"error": f"crm.lead id={lead_id} no existe"}

        config = env['cristal.agent.config'].sudo().get_active()
        bot_user_id = config.bot_user_id.id if config.bot_user_id else 721

        from odoo import fields as odoo_fields
        now = odoo_fields.Datetime.now()
        today = odoo_fields.Date.today()
        expected_delivery = _next_business_delivery(today)
        check_date = expected_delivery + timedelta(days=2)

        # Actualizar lead
        update_vals = {
            'agent_sample_sent_at': now,
            'agent_sample_expected_delivery': expected_delivery,
        }
        if lead.agent_strategy_phase == 'phase_1':
            update_vals['agent_strategy_phase'] = 'phase_2'
        if products_sample:
            existing_desc = lead.description or ''
            update_vals['description'] = (
                f"{existing_desc}\n[Muestra coordinada {now}] {products_sample}"
            ).strip()

        try:
            lead.write(update_vals)
        except Exception as e:
            _logger.exception("Error actualizando lead: %s", e)
            return {"error": f"No se pudo actualizar el lead: {e}"}

        # Agendar actividad "Chequeo post-muestra"
        activity_type = env['mail.activity.type'].sudo().search(
            [('name', '=', 'Iniciativa de venta')], limit=1
        )
        if not activity_type:
            activity_type = env['mail.activity.type'].sudo().browse(4)

        activity_id = None
        if activity_type.exists():
            try:
                activity = env['mail.activity'].sudo().create({
                    'res_model': 'crm.lead',
                    'res_model_id': env['ir.model']._get_id('crm.lead'),
                    'res_id': lead.id,
                    'activity_type_id': activity_type.id,
                    'user_id': bot_user_id,
                    'date_deadline': check_date,
                    'summary': f"Chequeo post-muestra {lead.partner_id.name or ''}".strip(),
                    'note': (
                        f"Muestra enviada el {now.strftime('%d/%m')}. "
                        f"Entrega estimada {expected_delivery.strftime('%d/%m')} "
                        f"({_weekday_es(expected_delivery)}). "
                        f"Preguntar si llegó y qué le pareció. Activar Fase 2 según respuesta."
                    ),
                })
                activity_id = activity.id
            except Exception as e:
                _logger.warning("No se pudo crear actividad: %s", e)

        # Actualizar partner si tiene fase
        if lead.partner_id and lead.partner_id.agent_strategy_phase == 'phase_1_qualifying':
            try:
                lead.partner_id.sudo().write({
                    'agent_strategy_phase': 'phase_2_post_sample',
                })
            except Exception:
                pass

        return {
            "ok": True,
            "lead_id": lead.id,
            "sample_sent_at": str(now),
            "expected_delivery": str(expected_delivery),
            "expected_delivery_weekday": _weekday_es(expected_delivery),
            "check_activity_id": activity_id,
            "check_scheduled_for": str(check_date),
            "summary": (
                f"Muestra registrada para {lead.partner_id.name}. "
                f"Entrega estimada: {expected_delivery.strftime('%d/%m')} "
                f"({_weekday_es(expected_delivery)}). "
                f"Chequeo agendado para {check_date.strftime('%d/%m')}."
            ),
        }


def _weekday_es(d):
    days = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
    return days[d.weekday()]
