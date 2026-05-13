# -*- coding: utf-8 -*-
"""
Clase base de las tools del agente.

Cada tool es una subclase de AgentTool con:
- name: identificador (snake_case) — visible para Claude
- description: qué hace (Claude la usa para decidir si llamarla)
- input_schema: JSON schema de los parámetros que acepta
- _execute(env, **kwargs): la implementación real

El decorador @ToolRegistry.register registra la subclase al importarse.
"""
import logging

_logger = logging.getLogger(__name__)


class AgentTool:
    """
    Clase base. Subclases deben definir name, description, input_schema y _execute.
    """

    name = None  # str
    description = None  # str
    input_schema = None  # dict (JSON Schema)

    def execute(self, env, run=None, **kwargs):
        """
        Wrapper que llama a _execute y captura excepciones uniformemente.
        Se llama desde el ClaudeClient.

        Args:
            env: el odoo.api.Environment
            run: el cristal.agent.run actual (puede ser None en algunos contextos)
            **kwargs: los argumentos del tool tal como Claude los pasó
        """
        if not self.name:
            raise NotImplementedError("La tool debe definir .name")

        # ═══ Check feature flag ═══
        try:
            from ..feature_flags import is_tool_enabled, get_disabled_message
            enabled, flag_name, label = is_tool_enabled(env, self.name)
            if not enabled:
                _logger.info(
                    "🚫 Tool '%s' DESHABILITADA (flag=%s). Devolviendo TOOL_DISABLED.",
                    self.name, flag_name
                )
                return {
                    "error": get_disabled_message(flag_name, label),
                    "tool_disabled": True,
                    "flag": flag_name,
                }
        except Exception as e:
            # Si la TX está abortada (típico tras race condition), rollback
            # y devolver error claro en vez de cascada de InFailedSqlTransaction.
            msg = str(e)
            if 'aborted' in msg.lower() or 'InFailedSqlTransaction' in msg:
                _logger.error(
                    "💀 Transacción ABORTADA detectada antes de %s. "
                    "Haciendo rollback para liberar tools siguientes.",
                    self.name,
                )
                try:
                    env.cr.rollback()
                except Exception:
                    pass
                return {
                    "error": f"Transacción abortada antes de {self.name} "
                             f"(probable race condition o conflicto SQL previo). "
                             f"Tool no se ejecutó. Reintentá el mensaje del cliente.",
                    "transaction_aborted": True,
                }
            _logger.warning("No se pudo chequear flag para %s: %s", self.name, e)

        try:
            return self._execute(env=env, run=run, **kwargs)
        except TypeError as e:
            _logger.warning("Tool %s recibió args inválidos: %s | kwargs=%s",
                            self.name, e, kwargs)
            return {
                "error": f"Argumentos inválidos para {self.name}: {str(e)}",
                "expected_schema": self.input_schema,
            }
        except Exception as e:
            msg = str(e)
            # Misma detección dentro del execute principal: si la TX se aborta
            # acá, rollback y mensaje claro al modelo.
            if 'aborted' in msg.lower() or 'InFailedSqlTransaction' in msg:
                _logger.error(
                    "💀 Transacción ABORTADA durante %s. Rollback aplicado.",
                    self.name,
                )
                try:
                    env.cr.rollback()
                except Exception:
                    pass
                return {
                    "error": f"Transacción abortada durante {self.name}. "
                             f"Tool no se ejecutó. Reintentá.",
                    "transaction_aborted": True,
                }
            _logger.exception("Tool %s falló durante execute: %s", self.name, e)
            return {"error": f"{self.name} falló: {str(e)}"}

    def _execute(self, env, run=None, **kwargs):
        """A implementar por cada subclase."""
        raise NotImplementedError(f"Tool {self.name} no implementó _execute")
