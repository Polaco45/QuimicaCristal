# -*- coding: utf-8 -*-
"""
Tool: ask_advanced_model (v1.42)

El modelo base (Haiku 5.5) pide que el resto de la corrida la siga el modelo
avanzado (anthropic_model_complex). El cambio de modelo lo hace ClaudeClient al ver
esta tool (no pasa por _execute); acá queda la definición para que el modelo la vea.
"""
from .base import AgentTool
from ..tool_registry import ToolRegistry


@ToolRegistry.register
class AskAdvancedModel(AgentTool):
    name = "ask_advanced_model"
    description = (
        "Pasá el caso a un modelo más capaz, que sigue la conversación con todo el "
        "contexto. Usalo ANTES de responder cuando: el cliente reclama o está molesto; "
        "no entendés bien qué pide; el pedido tiene muchos productos o condiciones; "
        "tenés que decidir algo comercial dudoso (descuento, excepción, entrega "
        "especial); o dos datos del contexto se contradicen. No lo uses para "
        "consultas simples (precio, stock, una cotización común)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Motivo en pocas palabras (ej: 'reclamo por bidón roto').",
            },
        },
        "required": ["reason"],
    }

    def _execute(self, env, run=None, reason=None, **kwargs):
        # Normalmente lo intercepta ClaudeClient; si llega acá, no hay cambio posible.
        return {"ok": False, "summary": "No hay modelo avanzado disponible: resolvé vos."}
