# -*- coding: utf-8 -*-
"""
Registro centralizado de tools disponibles para el agente.

Cada tool en el directorio tools/ se registra acá automáticamente al importarse.
El claude_client.py usa este registro para:
1. Generar la lista de tool definitions que se manda a Claude
2. Despachar la ejecución cuando Claude llama a un tool
"""
import logging

_logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registro de tools — singleton dentro del módulo."""

    _tools = {}

    @classmethod
    def register(cls, tool_class):
        """Decorador: registra una clase de tool."""
        instance = tool_class()
        if instance.name in cls._tools:
            _logger.warning("Tool %s ya estaba registrada, sobreescribiendo.", instance.name)
        cls._tools[instance.name] = instance
        _logger.debug("✅ Tool registrada: %s", instance.name)
        return tool_class

    @classmethod
    def get(cls, name):
        return cls._tools.get(name)

    @classmethod
    def all(cls):
        return list(cls._tools.values())

    @classmethod
    def names(cls):
        return list(cls._tools.keys())

    @classmethod
    def schemas_for_anthropic(cls, client_type=None):
        """
        Devuelve la lista de tool definitions en el formato que espera la API
        de Anthropic.

        v1.9.0: si client_type='institucional', filtra las tools que no aplican
        al flow institucional (ofertas, templates, niveles, muestras, etc).
        Si client_type='mayorista', oculta las tools dedicadas al flow
        institucional para que el bot mayorista no las llame por error.
        """
        # Tools EXCLUSIVAS del flow institucional. NO deben aparecer en mayorista.
        INSTITUTIONAL_ONLY = {
            'update_qualification_data',
            'complete_institutional_qualification',
        }

        # Tools que NO aplican al flow institucional. El agente institucional
        # solo necesita: buscar/leer/crear partners, leer historial, crear
        # leads y actividades, programar takeover, mandar WhatsApp libre,
        # consultar knowledge, + las 2 tools institucionales propias.
        INSTITUTIONAL_EXCLUDED = {
            'send_whatsapp_template',     # Templates de mayoristas
            'compute_partner_level',      # BRONCE/PLATA/ORO no aplica
            'set_partner_level',
            'search_offers',              # Ofertas mayoristas
            'confirm_sample_sent',        # Muestras (mayoristas)
            'create_sale_order',          # El cierre lo hace Joaco, no el bot
            'generate_pricelist_pdf',     # No mandamos precios al institucional
            'generate_quote_pdf',         # Cotización la hace Joaco
            'check_stock',                # No relevante para calificación
            'search_invoices',
            # NOTA: create_lead y schedule_activity quedan disponibles para el bot
            # institucional como respaldo, pero su uso normal es vía la tool atómica
            # complete_institutional_qualification.
        }

        tools = list(cls._tools.values())
        if client_type == 'institucional':
            tools = [t for t in tools if t.name not in INSTITUTIONAL_EXCLUDED]
        elif client_type == 'mayorista':
            tools = [t for t in tools if t.name not in INSTITUTIONAL_ONLY]

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]
