# -*- coding: utf-8 -*-
"""
Tool: read_partner

Lee los datos completos de un partner: contacto, etiquetas, observaciones
acumuladas, nivel mayorista, fase comercial, últimas compras, etc.
"""
import logging
from .base import AgentTool
from ..tool_registry import ToolRegistry

_logger = logging.getLogger(__name__)


@ToolRegistry.register
class ReadPartner(AgentTool):
    name = "read_partner"
    description = (
        "Lee los datos completos de un cliente. Te devuelve: nombre, contacto, "
        "etiquetas, lista de precios, dirección, nivel mayorista, fase comercial, "
        "observaciones acumuladas, última compra, historial resumido. "
        "Usalo cuando necesitás contexto completo del cliente para responderle bien."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "partner_id": {
                "type": "integer",
                "description": "ID del partner a leer.",
            },
        },
        "required": ["partner_id"],
    }

    def _execute(self, env, run=None, partner_id=None, **kwargs):
        if not partner_id:
            return {"error": "partner_id es obligatorio"}

        partner = env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return {"error": f"partner_id={partner_id} no existe"}

        # Direcciones (contactos hijos tipo delivery)
        addresses = []
        for child in partner.child_ids:
            if child.type == 'delivery':
                addresses.append({
                    'id': child.id,
                    'name': child.name,
                    'street': child.street or '',
                    'city': child.city or '',
                })

        # Última cotización / orden
        SaleOrder = env['sale.order'].sudo()
        last_order = SaleOrder.search([
            ('partner_id', '=', partner.id),
        ], order='date_order desc', limit=1)
        last_order_summary = None
        if last_order:
            last_order_summary = {
                'id': last_order.id,
                'name': last_order.name,
                'state': last_order.state,
                'date': str(last_order.date_order) if last_order.date_order else '',
                'amount_total': last_order.amount_total,
            }

        # Última factura
        Invoice = env['account.move'].sudo()
        last_invoice = Invoice.search([
            ('partner_id', '=', partner.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
        ], order='invoice_date desc', limit=1)
        last_invoice_summary = None
        if last_invoice:
            last_invoice_summary = {
                'id': last_invoice.id,
                'name': last_invoice.name,
                'date': str(last_invoice.invoice_date) if last_invoice.invoice_date else '',
                'amount_untaxed': last_invoice.amount_untaxed,
                'amount_total': last_invoice.amount_total,
                'payment_state': last_invoice.payment_state,
            }

        # Lead activo
        Lead = env['crm.lead'].sudo()
        active_lead = Lead.search([
            ('partner_id', '=', partner.id),
            ('active', '=', True),
            ('stage_id.is_won', '=', False),
        ], order='create_date desc', limit=1)
        active_lead_summary = None
        if active_lead:
            active_lead_summary = {
                'id': active_lead.id,
                'name': active_lead.name,
                'stage': active_lead.stage_id.name if active_lead.stage_id else '',
                'expected_revenue': active_lead.expected_revenue,
                'salesperson': active_lead.user_id.name if active_lead.user_id else '',
                'agent_strategy_phase': active_lead.agent_strategy_phase if hasattr(active_lead, 'agent_strategy_phase') else '',
            }

        # Buscar canal de WhatsApp activo del partner (para mandar mensajes proactivos)
        wa_channel = env['discuss.channel'].sudo().search([
            ('channel_type', '=', 'whatsapp'),
            ('channel_partner_ids', 'in', [partner.id]),
        ], limit=1, order='write_date desc')
        wa_channel_id = wa_channel.id if wa_channel else 0
        wa_account_id = 0
        if wa_channel and hasattr(wa_channel, 'wa_account_id') and wa_channel.wa_account_id:
            wa_account_id = wa_channel.wa_account_id.id

        return {
            "ok": True,
            "partner": {
                "id": partner.id,
                "name": partner.name or '',
                "is_company": partner.is_company,
                "mobile": partner.mobile or '',
                "phone": partner.phone or '',
                "email": partner.email or '',
                "vat": partner.vat or '',
                "street": partner.street or '',
                "city": partner.city or '',
                "categories": [c.name for c in partner.category_id],
                "category_ids": partner.category_id.ids,
                "pricelist": partner.property_product_pricelist.name if partner.property_product_pricelist else '',
                "pricelist_id": partner.property_product_pricelist.id if partner.property_product_pricelist else 0,
                # team_id NO es campo de res.partner — lo leemos del lead asociado si existe
                "team_id": self._get_team_id(env, partner),
                "team_name": self._get_team_name(env, partner),
                "delivery_addresses": addresses,

                # Canal WhatsApp del partner (CRÍTICO para mensajes proactivos)
                "whatsapp_channel_id": wa_channel_id,
                "whatsapp_account_id": wa_account_id,

                # Campos del agente
                "agent_level": partner.agent_level if hasattr(partner, 'agent_level') else 'none',
                "agent_strategy_phase": partner.agent_strategy_phase if hasattr(partner, 'agent_strategy_phase') else 'not_qualified',
                "agent_observations": partner.agent_observations if hasattr(partner, 'agent_observations') else '',
                "agent_monthly_volume_avg": partner.agent_monthly_volume_avg if hasattr(partner, 'agent_monthly_volume_avg') else 0,
                "agent_days_since_last_purchase": partner.agent_days_since_last_purchase if hasattr(partner, 'agent_days_since_last_purchase') else -1,

                # Resúmenes
                "last_order": last_order_summary,
                "last_invoice": last_invoice_summary,
                "active_lead": active_lead_summary,
            },
        }

    def _get_team_id(self, env, partner):
        """team_id no existe en res.partner — lo leemos del lead activo
        agent_managed del partner."""
        try:
            lead = env['crm.lead'].sudo().search([
                ('partner_id', '=', partner.id),
                ('agent_managed', '=', True),
                ('active', '=', True),
            ], limit=1, order='create_date desc')
            return lead.team_id.id if (lead and lead.team_id) else 0
        except Exception:
            return 0

    def _get_team_name(self, env, partner):
        try:
            lead = env['crm.lead'].sudo().search([
                ('partner_id', '=', partner.id),
                ('agent_managed', '=', True),
                ('active', '=', True),
            ], limit=1, order='create_date desc')
            return lead.team_id.name if (lead and lead.team_id) else ''
        except Exception:
            return ''
