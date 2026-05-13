# -*- coding: utf-8 -*-
"""
Servicio de Feature Flags.

Mapea cada tool a su flag de habilitación en cristal.agent.config.
Cuando el bot intenta ejecutar una tool deshabilitada, el dispatcher
devuelve un error específico al bot indicándole que la capacidad está
apagada y debe escalar.
"""
import logging

_logger = logging.getLogger(__name__)


# Mapping tool_name → campo boolean del config.
# Las tools NO listadas acá siempre están habilitadas (read-only, observation, etc).
TOOL_TO_FLAG = {
    # WhatsApp
    'send_whatsapp': 'enable_send_whatsapp',
    'send_whatsapp_template': 'enable_send_whatsapp_templates',

    # CRM
    'create_lead': 'enable_create_leads',
    'update_lead': 'enable_update_leads',
    'schedule_activity': 'enable_schedule_activities',
    'mark_activity_done': 'enable_schedule_activities',
    'escalate_to_joaco': 'enable_escalate_to_joaco',

    # Ventas
    'create_sale_order': 'enable_create_sale_orders',
    'generate_quote_pdf': 'enable_generate_quote_pdf',
    'generate_pricelist_pdf': 'enable_generate_pricelist_pdf',

    # Muestras
    'confirm_sample_sent': 'enable_confirm_sample',

    # Conocimiento
    'search_offers': 'enable_apply_offers',
    'add_knowledge': 'enable_internal_channel_learning',
}


# Las siguientes tools son SIEMPRE habilitadas (no dependen de flag):
# read_partner, search_partners, create_partner, update_partner, update_observation,
# read_message_history, search_knowledge, search_products, check_stock, search_orders,
# search_invoices, view_attachment, pause_bot, compute_partner_level, set_partner_level


def is_tool_enabled(env, tool_name):
    """
    Devuelve (enabled: bool, flag_name: str or None, label: str or None).

    Si la tool no tiene flag mapeado → siempre enabled=True.
    Si tiene flag → busca el valor en cristal.agent.config.
    """
    flag_name = TOOL_TO_FLAG.get(tool_name)
    if not flag_name:
        return True, None, None

    Config = env['cristal.agent.config'].sudo()
    config = Config.get_active()
    if not config:
        return True, flag_name, None

    enabled = bool(getattr(config, flag_name, True))
    # Resolver label legible
    label = None
    try:
        label = config._fields[flag_name].string
    except Exception:
        pass
    return enabled, flag_name, label


def get_disabled_message(flag_name, label=None):
    """Mensaje uniforme cuando una tool está deshabilitada."""
    label = label or flag_name
    return (
        f"TOOL_DISABLED: la capacidad '{label}' está apagada por Joaco "
        f"(config.{flag_name}=False). NO PUEDO ejecutar esta acción. "
        f"ESCALÁ a Joaco con `escalate_to_joaco` informando lo que ibas a hacer "
        f"para que él lo resuelva manualmente."
    )


def is_cron_enabled(env, cron_flag):
    """Para los crones — chequea su flag específico."""
    Config = env['cristal.agent.config'].sudo()
    config = Config.get_active()
    if not config:
        return False
    return bool(getattr(config, cron_flag, True))
