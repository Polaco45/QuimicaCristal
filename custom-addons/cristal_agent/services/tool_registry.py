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
    def schemas_for_anthropic(cls):
        """
        Devuelve la lista de tool definitions en el formato que espera la API
        de Anthropic. Cada tool debe tener: name, description, input_schema.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in cls._tools.values()
        ]
