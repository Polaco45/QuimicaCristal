# -*- coding: utf-8 -*-
"""
Cliente de Claude API.

Implementa el loop de tool_use:
    1. Mandamos a Claude el mensaje + tools disponibles
    2. Claude responde con tool_use blocks (o texto final)
    3. Si hay tool_use, ejecutamos cada tool y devolvemos los tool_results
    4. Repetimos hasta que stop_reason sea end_turn o llegamos a max_iterations

Cada ejecución se loguea en cristal.agent.run para auditoría.

Función pública principal:
    dispatch_agent_for_message(env, wa_message, partner, memory, plain_text)
"""
import json
import logging
import time

_logger = logging.getLogger(__name__)


def dispatch_agent_for_message(env, wa_message, partner, memory, plain_text):
    """
    Dispara el agente para procesar un mensaje WhatsApp entrante.

    Esta es la función pública que se llama desde models/whatsapp_message.py.
    """
    from .prompt_builder import build_system_prompt, build_user_message_for_whatsapp

    Run = env['cristal.agent.run'].sudo()

    # Identificar channel
    channel_id = wa_message.mail_message_id.res_id if wa_message.mail_message_id else False

    # Crear log de ejecución
    run = Run.create({
        'trigger': 'whatsapp_message',
        'partner_id': partner.id,
        'channel_id': channel_id if channel_id else False,
        'incoming_message_id': wa_message.mail_message_id.id if wa_message.mail_message_id else False,
        'incoming_text': plain_text,
        'state': 'running',
    })

    try:
        # v1.9.0 — Detectar client_type del memory (ya está seteado por
        # el pipeline en whatsapp_message.py antes de llegar acá).
        client_type = memory.client_type if memory and memory.client_type else None

        # Construir prompts
        system_prompt = build_system_prompt(env, partner=partner, client_type=client_type)
        user_message = build_user_message_for_whatsapp(env, wa_message, partner, plain_text)

        # Ejecutar el loop
        client = ClaudeClient(env, run=run, client_type=client_type)
        result = client.run_conversation(
            system_prompt=system_prompt,
            user_message=user_message,
        )

        # Marcar OK
        run.mark_done(final_response=result.get('final_text', ''))
        return result

    except Exception as e:
        _logger.exception("Error en dispatch_agent_for_message: %s", e)
        run.mark_error(str(e))
        return None


def dispatch_agent_for_cron(env, trigger, partner, cron_type, extra_context=None):
    """Dispara el agente para una activación por cron."""
    from .prompt_builder import build_system_prompt, build_user_message_for_cron

    Run = env['cristal.agent.run'].sudo()
    run = Run.create({
        'trigger': trigger,
        'partner_id': partner.id if partner else False,
        'state': 'running',
    })

    try:
        system_prompt = build_system_prompt(env, partner=partner)
        user_message = build_user_message_for_cron(env, partner, cron_type, extra_context)

        client = ClaudeClient(env, run=run)
        result = client.run_conversation(
            system_prompt=system_prompt,
            user_message=user_message,
        )

        run.mark_done(final_response=result.get('final_text', ''))
        return result

    except Exception as e:
        _logger.exception("Error en dispatch_agent_for_cron: %s", e)
        run.mark_error(str(e))
        return None


def dispatch_agent_for_activity(env, partner, lead, activity):
    """
    Dispara el agente para cumplir una actividad pendiente (cron proactivo).

    El agente recibe:
    - El partner
    - El lead activo (si lo hay)
    - El summary + note de la actividad

    Su trabajo: decidir qué hacer (mandar mensaje al cliente, ofrecer algo,
    escalar, etc.), ejecutarlo, marcar la actividad como done con
    mark_activity_done, y agendar la siguiente con schedule_activity.
    """
    from .prompt_builder import build_system_prompt

    Run = env['cristal.agent.run'].sudo()
    run = Run.create({
        'trigger': 'cron_cadence',
        'partner_id': partner.id if partner else False,
        'state': 'running',
        'incoming_text': f"[ACTIVIDAD #{activity.id}] {activity.summary or ''}",
    })

    try:
        system_prompt = build_system_prompt(env, partner=partner)

        # ═══ Resolver channel_id, wa_account_id y mobile del cliente ═══
        # Antes el bot tenía que buscarlos solo y a veces no los encontraba.
        # Ahora se los pasamos directamente en el contexto.
        Channel = env['discuss.channel'].sudo()
        wa_channel = None
        wa_account_id = None
        # Buscar canal WhatsApp del partner
        try:
            wa_channel = Channel.search([
                ('channel_type', '=', 'whatsapp'),
                ('channel_partner_ids', 'in', [partner.id]),
            ], limit=1, order='write_date desc')
            if wa_channel and hasattr(wa_channel, 'wa_account_id') and wa_channel.wa_account_id:
                wa_account_id = wa_channel.wa_account_id.id
        except Exception:
            pass

        channel_info = ""
        if wa_channel:
            channel_info = (
                f"\n=== Canal WhatsApp del cliente (DATOS LISTOS — NO los busques de nuevo) ===\n"
                f"channel_id: {wa_channel.id}\n"
                f"wa_account_id: {wa_account_id or 'N/A'}\n"
                f"mobile_number: {partner.mobile or partner.phone or 'N/A'}\n"
                f"Usá EXACTAMENTE estos valores en send_whatsapp / send_whatsapp_template.\n"
            )
        else:
            channel_info = (
                f"\n=== Canal WhatsApp del cliente ===\n"
                f"⚠️ NO se encontró canal WhatsApp activo para este cliente. "
                f"NO PUEDAS mandar mensajes WhatsApp directamente. "
                f"ESCALÁ a Joaco con `escalate_to_joaco` resumiendo qué corresponde hacer.\n"
            )

        # Construir user_message con el contexto de la actividad
        lead_info = ""
        if lead and lead.exists():
            lead_info = (
                f"Lead activo: #{lead.id} \"{lead.name}\"\n"
                f"  Fase actual: {dict(lead._fields['agent_strategy_phase'].selection).get(lead.agent_strategy_phase, '—')}\n"
                f"  Stage CRM: {lead.stage_id.name if lead.stage_id else '—'}\n"
            )
            if lead.agent_sample_sent_at:
                lead_info += f"  Muestra enviada: {lead.agent_sample_sent_at}\n"
            if lead.agent_sample_expected_delivery:
                lead_info += f"  Entrega prevista: {lead.agent_sample_expected_delivery}\n"

        user_message = (
            "MODO: EJECUCIÓN PROACTIVA DE ACTIVIDAD PENDIENTE\n\n"
            f"Tenés una actividad pendiente que vence hoy o ya venció.\n\n"
            f"=== Cliente ===\n"
            f"Partner: {partner.name} (id={partner.id})\n"
            f"Teléfono: {partner.mobile or partner.phone or 'N/A'}\n"
            f"Email: {partner.email or 'N/A'}\n"
            f"Fase: {partner.agent_strategy_phase or 'sin asignar'}\n"
            f"Nivel: {partner.agent_level or 'sin nivel'}\n"
            f"Observaciones previas: {(partner.agent_observations or 'ninguna')[:300]}\n"
            f"\n=== Lead ===\n"
            f"{lead_info or 'Sin lead activo.'}"
            f"{channel_info}"
            f"\n=== Actividad ===\n"
            f"ID: {activity.id}\n"
            f"Tipo: {activity.activity_type_id.name if activity.activity_type_id else '—'}\n"
            f"Deadline: {activity.date_deadline}\n"
            f"Resumen: {activity.summary or '—'}\n"
            f"Nota: {activity.note or '—'}\n\n"
            "TU TAREA (en este orden):\n"
            "1. Leé el historial reciente con `read_message_history(channel_id=" + str(wa_channel.id if wa_channel else 0) + ", limit=10)`\n"
            "2. Decidí qué hacer SEGÚN LA FASE Y EL CONTEXTO:\n"
            "   - Fase 2 post-muestra → mandar chequeo \"¿pudiste probar?\"\n"
            "   - Fase 3 → cadencia post-compra\n"
            "   - Si no estás seguro → ESCALAR a Joaco\n"
            "3. Ejecutá la acción: `send_whatsapp` al cliente con mensaje natural y corto\n"
            "4. Llamá a `update_observation` con lo que hiciste\n"
            "5. OBLIGATORIO: `mark_activity_done(activity_id=" + str(activity.id) + ")`\n"
            "6. Llamá a `schedule_activity` para el siguiente paso\n\n"
            "Tono natural de vendedor. NO sobreactuar. Máximo 3 líneas."
        )

        client = ClaudeClient(env, run=run)
        result = client.run_conversation(
            system_prompt=system_prompt,
            user_message=user_message,
        )

        run.mark_done(final_response=result.get('final_text', ''))
        return result

    except Exception as e:
        _logger.exception("Error en dispatch_agent_for_activity: %s", e)
        run.mark_error(str(e))
        return None


def dispatch_agent_for_internal_message(env, channel, plain_text, mail_message_id=None):
    """
    Dispara el agente cuando Joaco escribe en el canal interno (id 969).

    Modos posibles que el agente debe identificar y ejecutar:
    - Enseñanza: "anotate que...", "a partir de hoy...", "recordá X" → usar add_knowledge
    - Comando: "comunicate con X", "mandale tal cosa a Y" → ejecutar la acción
    - Pregunta: "¿cuántos clientes Plata tenés?" → responder en el canal interno
    - Feedback sobre escalación previa: "lo manejo yo / comunicate vos" → ejecutar
    """
    from .prompt_builder import build_system_prompt

    Run = env['cristal.agent.run'].sudo()
    run = Run.create({
        'trigger': 'joaco_command',
        'channel_id': channel.id,
        'incoming_message_id': mail_message_id if mail_message_id else False,
        'incoming_text': plain_text,
        'state': 'running',
    })

    try:
        # System prompt sin partner_id (porque es chat interno, no de un cliente)
        system_prompt = build_system_prompt(env, partner=None)

        # Construimos el user message con instrucciones específicas para modo interno
        user_message = (
            "MODO: CHAT INTERNO CON JOACO\n\n"
            f"channel_id (canal interno Joaco↔Claudio): {channel.id}\n"
            f"mail_message_id del mensaje de Joaco: {mail_message_id or 'N/A'}\n\n"
            f"Joaco te escribió en el canal interno:\n"
            f'"{plain_text}"\n\n'
            "OBLIGATORIO: lo PRIMERO que hacés es leer el historial reciente del canal "
            f"con read_message_history(channel_id={channel.id}, limit=20). "
            "Necesitás CONTEXTO antes de actuar — quizás Joaco se está refiriendo a una "
            "escalación anterior tuya, a un cliente puntual, etc.\n\n"
            "Después decidís qué hacer:\n"
            "1. Si es una ENSEÑANZA (anotate que X, a partir de hoy Y, recordá Z) → "
            "guardala con add_knowledge en la categoría apropiada.\n"
            "2. Si es un COMANDO sobre un cliente (comunicate vos, mandale X a Y) → "
            "identificá al cliente (search_partners por nombre o usá el partner_id "
            "del mensaje anterior tuyo), y ejecutá la acción (típicamente send_whatsapp "
            "al cliente). Joaco confía en vos, no le pidas confirmación.\n"
            "3. Si es una PREGUNTA → respondele en el canal interno con send_internal_message "
            "(usá send_whatsapp con channel_id=" + str(channel.id) + " — el módulo lo trata "
            "como mensaje interno automáticamente).\n"
            "4. Si NO entendés la intención → preguntale a Joaco UNA cosa puntual.\n\n"
            "IMPORTANTE: Cuando termines de actuar, postea un resumen breve en el canal "
            "interno para que Joaco vea qué hiciste (ej: 'Hecho — le mandé a Franco la "
            "pregunta sobre productos y litros, y guardé la regla en KB.'). "
            "Para postear en el canal interno usá send_whatsapp con channel_id="
            + str(channel.id) + " y wa_account_id=0 (o cualquier valor — el canal es "
            "interno, no requiere cuenta WA real). Si send_whatsapp falla por wa_account, "
            "como fallback usá escalate_to_joaco con un mensaje de status."
        )

        client = ClaudeClient(env, run=run)
        result = client.run_conversation(
            system_prompt=system_prompt,
            user_message=user_message,
        )

        run.mark_done(final_response=result.get('final_text', ''))
        return result

    except Exception as e:
        _logger.exception("Error en dispatch_agent_for_internal_message: %s", e)
        run.mark_error(str(e))
        return None


class ClaudeClient:
    """
    Cliente de Claude API con manejo del loop de tool_use.

    Se instancia por cada conversación del agente. Cada instancia conoce
    su run (para loguear todo).
    """

    def __init__(self, env, run=None, client_type=None):
        self.env = env
        self.run = run
        # v1.9.0 — Filtra tools por client_type. Si None, todas las tools.
        self.client_type = client_type
        self.config = env['cristal.agent.config'].sudo().get_active()
        self.api_key = self.env['cristal.agent.config'].sudo().get_api_key()

        if not self.api_key:
            raise RuntimeError(
                "No hay API key de Anthropic configurada. "
                "Configurala en Cristal Agent → Configuración."
            )

        # Importamos requests acá para fallar temprano si no está
        try:
            import requests
        except ImportError:
            raise RuntimeError(
                "Falta el paquete Python 'requests'. "
                "Instalalo con: pip install requests"
            )
        self._requests = requests

        # Importamos los tools (esto los registra en el ToolRegistry)
        from . import tools  # noqa: F401
        from .tool_registry import ToolRegistry
        self.tool_registry = ToolRegistry

    def run_conversation(self, system_prompt, user_message):
        """
        Ejecuta el loop de conversación con Claude hasta que termine.

        Returns:
            dict: {'final_text': str, 'iterations': int, 'tool_calls': int, 'usage': dict}
        """
        start_time = time.time()
        messages = [{"role": "user", "content": user_message}]
        iterations = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_creation = 0
        total_cache_read = 0
        total_tool_calls = 0
        final_text = ""

        while iterations < self.config.max_iterations:
            iterations += 1
            _logger.debug("🔄 Iteración %s. Mensajes en contexto: %s", iterations, len(messages))

            # Llamada a Claude
            response = self._call_claude_api(system_prompt, messages)

            # Sumar tokens
            usage = response.get('usage', {})
            total_input_tokens += usage.get('input_tokens', 0)
            total_output_tokens += usage.get('output_tokens', 0)
            total_cache_creation += usage.get('cache_creation_input_tokens', 0)
            total_cache_read += usage.get('cache_read_input_tokens', 0)

            # Extraer texto y tool_uses de la respuesta
            content_blocks = response.get('content', [])
            assistant_text_parts = []
            tool_uses = []
            for block in content_blocks:
                if block.get('type') == 'text':
                    assistant_text_parts.append(block.get('text', ''))
                elif block.get('type') == 'tool_use':
                    tool_uses.append(block)

            # Agregamos el assistant message al contexto
            messages.append({"role": "assistant", "content": content_blocks})

            stop_reason = response.get('stop_reason')

            # Si NO hay tool_uses, terminamos
            if not tool_uses or stop_reason == 'end_turn':
                final_text = "".join(assistant_text_parts).strip()
                _logger.info("🏁 Loop terminado. stop_reason=%s, iter=%s, tool_calls=%s",
                             stop_reason, iterations, total_tool_calls)
                break

            # Ejecutar todos los tool_uses y armar tool_results
            tool_results_blocks = []
            for tu in tool_uses:
                total_tool_calls += 1
                tool_name = tu.get('name')
                tool_input = tu.get('input', {})
                tool_use_id = tu.get('id')

                _logger.info("🔧 Ejecutando tool: %s", tool_name)

                tool_start = time.time()
                try:
                    result = self._execute_tool(tool_name, tool_input)
                    is_error = False
                except Exception as e:
                    _logger.exception("Tool %s falló: %s", tool_name, e)
                    result = {"error": str(e)}
                    is_error = True
                tool_duration_ms = int((time.time() - tool_start) * 1000)

                # Loguear en el run
                if self.run:
                    self.run.append_tool_call(
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_output=result,
                        duration_ms=tool_duration_ms,
                        is_error=is_error,
                    )

                # Anthropic espera el tool_result en formato específico
                result_str = json.dumps(result, ensure_ascii=False, default=str) \
                    if not isinstance(result, str) else result
                tool_results_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result_str,
                    "is_error": is_error,
                })

            # Mandamos los tool_results como user message para la siguiente iteración
            messages.append({"role": "user", "content": tool_results_blocks})

        else:
            _logger.warning("⚠️ Se alcanzó max_iterations (%s) sin terminar", self.config.max_iterations)
            final_text = (final_text or
                          f"[Agente cortado por límite de {self.config.max_iterations} iteraciones]")

        duration = time.time() - start_time

        # Loguear en el run final
        if self.run:
            self.run.write({
                'iterations': iterations,
                'total_tool_calls': total_tool_calls,
                'input_tokens': total_input_tokens,
                'output_tokens': total_output_tokens,
                'cache_creation_input_tokens': total_cache_creation,
                'cache_read_input_tokens': total_cache_read,
                'duration_seconds': round(duration, 2),
                'final_response': final_text,
            })
            self.run.set_full_messages(messages)

        return {
            'final_text': final_text,
            'iterations': iterations,
            'tool_calls': total_tool_calls,
            'usage': {
                'input_tokens': total_input_tokens,
                'output_tokens': total_output_tokens,
                'cache_creation_input_tokens': total_cache_creation,
                'cache_read_input_tokens': total_cache_read,
            },
            'duration_seconds': duration,
        }

    def _call_claude_api(self, system_prompt, messages):
        """Hace una llamada HTTP a la API de Claude, con retry en caso de 429."""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.config.anthropic_version,
            "content-type": "application/json",
        }

        # System con cache control si está habilitado
        if self.config.enable_prompt_caching:
            system_param = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            system_param = system_prompt

        # Tools: si caching está prendido, marcamos la ÚLTIMA tool con cache_control.
        # v1.9.0 — Filtramos por client_type si aplica.
        tools_param = self.tool_registry.schemas_for_anthropic(client_type=self.client_type)
        if self.config.enable_prompt_caching and tools_param:
            # Copiar la última tool y agregarle cache_control
            tools_param = list(tools_param)
            last_tool = dict(tools_param[-1])
            last_tool['cache_control'] = {"type": "ephemeral"}
            tools_param[-1] = last_tool

        body = {
            "model": self.config.anthropic_model,
            "max_tokens": self.config.max_tokens,
            "system": system_param,
            "messages": messages,
            "tools": tools_param,
        }

        if self.config.temperature is not None:
            body["temperature"] = self.config.temperature

        # Retry con backoff exponencial: 0s → 8s → 24s → 60s
        max_attempts = 4
        backoff_seconds = [0, 8, 24, 60]
        last_error = None

        for attempt in range(max_attempts):
            if attempt > 0:
                wait = backoff_seconds[attempt]
                _logger.warning(
                    "⏳ Rate limit hit. Retry %s/%s en %ss...",
                    attempt, max_attempts - 1, wait
                )
                time.sleep(wait)

            try:
                resp = self._requests.post(
                    self.config.anthropic_api_url,
                    headers=headers,
                    json=body,
                    timeout=120,  # 2 min timeout por llamada
                )
            except self._requests.exceptions.Timeout:
                raise RuntimeError("Timeout llamando a Claude API (>120s)")
            except Exception as e:
                last_error = e
                continue

            # Status 429 → rate limit → reintentar con backoff
            if resp.status_code == 429:
                last_error = f"Rate limit 429: {resp.text[:200]}"
                _logger.warning("⚠️ %s", last_error)
                # Si la respuesta tiene Retry-After header, usarlo
                retry_after = resp.headers.get('retry-after')
                if retry_after and attempt < max_attempts - 1:
                    try:
                        backoff_seconds[attempt + 1] = max(int(retry_after), backoff_seconds[attempt + 1])
                    except (ValueError, IndexError):
                        pass
                continue  # reintenta

            # Otros errores: cortar
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Claude API devolvió {resp.status_code}: {resp.text[:500]}"
                )

            # Éxito
            return resp.json()

        # Se acabaron los retries
        raise RuntimeError(
            f"Claude API: rate limit persistente después de {max_attempts} intentos. "
            f"Último error: {last_error}. "
            f"Considerá subir tier en console.anthropic.com → Settings → Limits."
        )

    def _execute_tool(self, tool_name, tool_input):
        """Despacha la ejecución de un tool al registry."""
        tool = self.tool_registry.get(tool_name)
        if not tool:
            return {
                "error": f"Tool '{tool_name}' no existe. Tools disponibles: {self.tool_registry.names()}"
            }

        # Pasamos el env y opcionalmente el run a la tool
        return tool.execute(env=self.env, run=self.run, **tool_input)
