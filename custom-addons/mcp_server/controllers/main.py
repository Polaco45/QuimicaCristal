import json
import base64
import uuid
import logging
from datetime import datetime

from odoo import http, fields, SUPERUSER_ID
from odoo.http import request, Response
from odoo.exceptions import AccessError, ValidationError, UserError, MissingError

_logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "odoo-mcp-server"
SERVER_VERSION = "1.1.0"

# ============================================================
# Tool Definitions (MCP schema)
# ============================================================

TOOLS = [
    {
        "name": "list_models",
        "description": (
            "Lista todos los modelos de Odoo habilitados para operaciones MCP. "
            "Devuelve nombre técnico, nombre legible y permisos CRUD disponibles."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_model_fields",
        "description": (
            "Obtiene los campos y su metadata de un modelo de Odoo. "
            "Útil para saber qué campos usar en search/create/update."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Nombre técnico del modelo (ej: 'res.partner', 'sale.order')",
                },
            },
            "required": ["model"],
        },
    },
    {
        "name": "search_records",
        "description": (
            "Busca registros en un modelo de Odoo con filtros opcionales. "
            "Usa dominio estilo Odoo: [[\"campo\", \"operador\", valor]]. "
            "Operadores: =, !=, >, <, >=, <=, like, ilike, in, not in, child_of. "
            "Ejemplo: [[\"is_company\", \"=\", true], [\"country_id.code\", \"=\", \"AR\"]]"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Nombre técnico del modelo (ej: 'res.partner')",
                },
                "domain": {
                    "type": "array",
                    "description": "Filtros estilo Odoo. Default: [] (todos los registros)",
                    "default": [],
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Campos a devolver. Default: campos principales del modelo",
                },
                "limit": {
                    "type": "integer",
                    "description": "Máx registros a devolver. Default: 20",
                    "default": 20,
                },
                "offset": {
                    "type": "integer",
                    "description": "Registros a saltar (paginación). Default: 0",
                    "default": 0,
                },
                "order": {
                    "type": "string",
                    "description": "Orden de resultados (ej: 'name asc', 'create_date desc')",
                },
            },
            "required": ["model"],
        },
    },
    {
        "name": "read_record",
        "description": (
            "Lee un registro específico por su ID. "
            "Devuelve todos los campos permitidos o los especificados."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Nombre técnico del modelo",
                },
                "record_id": {
                    "type": "integer",
                    "description": "ID del registro a leer",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Campos a devolver. Default: campos principales",
                },
            },
            "required": ["model", "record_id"],
        },
    },
    {
        "name": "create_record",
        "description": (
            "Crea un nuevo registro en un modelo de Odoo. "
            "Devuelve el ID y nombre del registro creado."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Nombre técnico del modelo",
                },
                "values": {
                    "type": "object",
                    "description": (
                        "Valores para el nuevo registro como pares campo:valor. "
                        "Para many2one, usar el ID numérico. "
                        "Ejemplo: {\"name\": \"Juan\", \"email\": \"juan@test.com\", \"country_id\": 10}"
                    ),
                },
            },
            "required": ["model", "values"],
        },
    },
    {
        "name": "update_record",
        "description": (
            "Actualiza un registro existente en Odoo. "
            "Solo modifica los campos especificados."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Nombre técnico del modelo",
                },
                "record_id": {
                    "type": "integer",
                    "description": "ID del registro a actualizar",
                },
                "values": {
                    "type": "object",
                    "description": "Valores a actualizar como pares campo:valor",
                },
            },
            "required": ["model", "record_id", "values"],
        },
    },
    {
        "name": "delete_record",
        "description": (
            "Elimina un registro de Odoo. "
            "PRECAUCIÓN: esta operación puede ser irreversible. "
            "Si el modelo tiene campo 'active', se recomienda usar update_record "
            "con {\"active\": false} en su lugar."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Nombre técnico del modelo",
                },
                "record_id": {
                    "type": "integer",
                    "description": "ID del registro a eliminar",
                },
            },
            "required": ["model", "record_id"],
        },
    },
    {
        "name": "count_records",
        "description": "Cuenta registros que coinciden con un dominio.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Nombre técnico del modelo",
                },
                "domain": {
                    "type": "array",
                    "description": "Filtros estilo Odoo. Default: [] (contar todos)",
                    "default": [],
                },
            },
            "required": ["model"],
        },
    },
    # ----------------------------------------------------------
    # NUEVAS TOOLS (v1.1)
    # ----------------------------------------------------------
    {
        "name": "list_reports",
        "description": (
            "Lista los reportes de Odoo permitidos para ser ejecutados via MCP. "
            "Cada reporte tiene un xml_id que se usa con generate_report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "generate_report",
        "description": (
            "Genera un PDF de un reporte de Odoo y lo guarda como ir.attachment. "
            "Devuelve el attachment_id que luego se puede vincular a un mensaje "
            "(via attachment_ids del mail.message) o adjuntar a un registro. "
            "Solo se pueden ejecutar reportes registrados en mcp.report.access. "
            "Usá list_reports para ver los disponibles."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_xml_id": {
                    "type": "string",
                    "description": "XML ID del reporte (ej: 'product.action_report_pricelist')",
                },
                "record_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "IDs de los registros sobre los que generar el reporte",
                },
                "data": {
                    "type": "object",
                    "description": (
                        "Diccionario opcional con parámetros para el reporte. "
                        "Ej para lista de precios: {\"pricelist_id\": 6, \"quantities\": [1]}"
                    ),
                },
                "filename": {
                    "type": "string",
                    "description": "Nombre del archivo resultante. Default: usa el nombre del reporte.",
                },
            },
            "required": ["report_xml_id", "record_ids"],
        },
    },
    {
        "name": "get_unanswered_messages",
        "description": (
            "Devuelve los canales de WhatsApp con mensajes entrantes pendientes de respuesta. "
            "Lee de la cola mantenida por el cron MCP (mcp.pending.message). "
            "Cada entrada incluye: canal, último mensaje, autor, fecha, y resumen del cuerpo. "
            "Usá esto para arrancar una sesión de atención: '¿qué tengo sin contestar?'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Máx entradas a devolver. Default: 20",
                    "default": 20,
                },
                "include_in_progress": {
                    "type": "boolean",
                    "description": "Incluir conversaciones marcadas 'en atención'. Default: false",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "mark_message_handled",
        "description": (
            "Marca un canal como atendido en la cola de mensajes pendientes. "
            "Uso típico: después de responder a un cliente, llamar mark_message_handled "
            "con el channel_id para sacarlo de la cola activa."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "integer",
                    "description": "ID del discuss.channel a marcar como atendido",
                },
                "state": {
                    "type": "string",
                    "enum": ["done", "ignored", "in_progress", "pending"],
                    "description": "Estado destino. Default: 'done'",
                    "default": "done",
                },
            },
            "required": ["channel_id"],
        },
    },
]


# ============================================================
# Helper functions
# ============================================================

def _smart_fields(model_obj, max_fields=20):
    """Seleccionar campos 'inteligentes' - los más importantes del modelo"""
    priority_fields = [
        'name', 'display_name', 'active', 'state', 'stage_id',
        'partner_id', 'user_id', 'company_id', 'date', 'date_order',
        'email', 'phone', 'mobile', 'street', 'city', 'country_id',
        'amount_total', 'amount_untaxed', 'amount_tax', 'price_unit',
        'product_id', 'quantity', 'qty_available', 'list_price',
        'categ_id', 'type', 'sale_ok', 'purchase_ok',
        'invoice_status', 'payment_state', 'move_type',
        'create_date', 'write_date',
    ]
    all_fields = model_obj.fields_get()
    result = []
    # First add priority fields that exist
    for f in priority_fields:
        if f in all_fields and len(result) < max_fields:
            result.append(f)
    # Then add other non-relational fields
    for fname, finfo in all_fields.items():
        if fname in result or fname.startswith('_'):
            continue
        if finfo.get('type') in ('char', 'text', 'integer', 'float',
                                  'monetary', 'boolean', 'date', 'datetime',
                                  'selection'):
            result.append(fname)
        elif finfo.get('type') == 'many2one':
            result.append(fname)
        if len(result) >= max_fields:
            break
    return result


def _format_value(value):
    """Formatear un valor de Odoo para JSON"""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        # many2one: (id, name)
        return {"id": value[0], "display": value[1]}
    if isinstance(value, bytes):
        return "<binary data>"
    if value is False:
        return None
    return value


def _format_records(records_data):
    """Formatear registros para salida legible"""
    formatted = []
    for rec in records_data:
        formatted_rec = {}
        for key, val in rec.items():
            formatted_rec[key] = _format_value(val)
        formatted.append(formatted_rec)
    return formatted


# ============================================================
# Main MCP Controller
# ============================================================

class MCPController(http.Controller):

    def _get_api_key(self, token):
        """Validate API key token and return the record or None"""
        try:
            env = request.env(user=SUPERUSER_ID)
            api_key = env['mcp.api.key'].search([
                ('key', '=', token),
                ('active', '=', True),
            ], limit=1)
            return api_key if api_key else None
        except Exception:
            return None

    def _check_enabled(self):
        """Check if MCP server is enabled globally"""
        try:
            env = request.env(user=SUPERUSER_ID)
            enabled = env['ir.config_parameter'].get_param(
                'mcp_server.enabled', 'True'
            )
            return enabled.lower() in ('true', '1', 'yes')
        except Exception:
            return True

    def _json_rpc_response(self, msg_id, result, session_id=None):
        """Build a JSON-RPC 2.0 success response"""
        data = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": result,
        }
        headers = {'Content-Type': 'application/json'}
        if session_id:
            headers['Mcp-Session-Id'] = session_id
        return Response(json.dumps(data, default=str, ensure_ascii=False),
                        status=200, headers=headers)

    def _json_rpc_error(self, msg_id, code, message, status=200, session_id=None):
        """Build a JSON-RPC 2.0 error response"""
        data = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }
        headers = {'Content-Type': 'application/json'}
        if session_id:
            headers['Mcp-Session-Id'] = session_id
        return Response(json.dumps(data, default=str, ensure_ascii=False),
                        status=status, headers=headers)

    def _tool_result(self, msg_id, content_text, is_error=False):
        """Build a tools/call result"""
        return self._json_rpc_response(msg_id, {
            "content": [{"type": "text", "text": content_text}],
            "isError": is_error,
        })

    # ----------------------------------------------------------
    # Main HTTP endpoint
    # ----------------------------------------------------------

    @http.route(
        ['/mcp/<token>', '/mcp/<token>/'],
        type='http', auth='none', methods=['POST', 'GET', 'DELETE'],
        csrf=False, cors='*', save_session=False,
    )
    def mcp_endpoint(self, token, **kwargs):
        """
        Main MCP Streamable HTTP endpoint.
        Token in URL for authentication (compatible with Claude.ai Custom Connectors).
        """
        # --- Preflight / health check ---
        if request.httprequest.method == 'GET':
            return Response(
                json.dumps({"status": "ok", "server": SERVER_NAME, "version": SERVER_VERSION}),
                status=200, headers={'Content-Type': 'application/json'},
            )

        # --- Check global enable ---
        if not self._check_enabled():
            return self._json_rpc_error(
                None, -32001, "MCP Server está deshabilitado", status=503)

        # --- Authenticate ---
        api_key = self._get_api_key(token)
        if not api_key:
            return self._json_rpc_error(
                None, -32001, "API Key inválida o inactiva", status=401)

        # --- DELETE: end session ---
        if request.httprequest.method == 'DELETE':
            return Response('', status=200)

        # --- POST: handle MCP message ---
        try:
            raw_body = request.httprequest.get_data(as_text=True)
            body = json.loads(raw_body)
        except (json.JSONDecodeError, Exception) as e:
            return self._json_rpc_error(None, -32700, f"Error de parseo JSON: {e}")

        method = body.get('method', '')
        msg_id = body.get('id')
        params = body.get('params', {})
        session_id = request.httprequest.headers.get('Mcp-Session-Id')

        # Log request
        try:
            env = request.env(user=SUPERUSER_ID)
            log_enabled = env['ir.config_parameter'].get_param(
                'mcp_server.log_requests', 'True'
            )
            if log_enabled.lower() in ('true', '1', 'yes'):
                _logger.info("MCP [%s] method=%s params_keys=%s",
                             api_key.name, method, list(params.keys()))
        except Exception:
            pass

        # Track usage
        try:
            api_key._log_usage()
        except Exception:
            pass

        # Generate session if needed
        if not session_id:
            session_id = str(uuid.uuid4())

        # --- Route to handler ---
        try:
            # Switch to the API key's user for ORM operations
            user_env = request.env(user=api_key.user_id.id)

            if method == 'initialize':
                return self._handle_initialize(msg_id, params, session_id)

            elif method == 'notifications/initialized':
                return Response('', status=202,
                                headers={'Mcp-Session-Id': session_id})

            elif method == 'ping':
                return self._json_rpc_response(msg_id, {}, session_id)

            elif method == 'tools/list':
                return self._handle_tools_list(msg_id, session_id)

            elif method == 'tools/call':
                return self._handle_tools_call(msg_id, params, user_env, session_id)

            elif method == 'resources/list':
                # We don't expose resources, just tools
                return self._json_rpc_response(msg_id, {"resources": []}, session_id)

            elif method == 'prompts/list':
                return self._json_rpc_response(msg_id, {"prompts": []}, session_id)

            else:
                return self._json_rpc_error(
                    msg_id, -32601, f"Método no soportado: {method}",
                    session_id=session_id)

        except AccessError as e:
            _logger.warning("MCP AccessError: %s", e)
            return self._json_rpc_error(
                msg_id, -32001, f"Sin permisos: {e}", session_id=session_id)
        except Exception as e:
            _logger.exception("MCP error handling method=%s", method)
            return self._json_rpc_error(
                msg_id, -32603, f"Error interno: {e}", session_id=session_id)

    # ----------------------------------------------------------
    # Also support Bearer token auth in Authorization header
    # ----------------------------------------------------------

    @http.route(
        ['/mcp', '/mcp/'],
        type='http', auth='none', methods=['POST', 'GET', 'DELETE'],
        csrf=False, cors='*', save_session=False,
    )
    def mcp_endpoint_bearer(self, **kwargs):
        """
        Alternative endpoint using Bearer token in Authorization header.
        Compatible with Claude Code and other MCP clients.
        """
        auth_header = request.httprequest.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
        else:
            return self._json_rpc_error(
                None, -32001,
                "Falta el token. Usá /mcp/<token> o Authorization: Bearer <token>",
                status=401,
            )
        return self.mcp_endpoint(token, **kwargs)

    # ----------------------------------------------------------
    # Protocol Handlers
    # ----------------------------------------------------------

    def _handle_initialize(self, msg_id, params, session_id):
        """Handle the MCP initialize handshake"""
        return self._json_rpc_response(msg_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
            "instructions": (
                "Este servidor MCP conecta con Odoo ERP (Química Cristal). "
                "Podés buscar, crear, editar y eliminar registros en los modelos habilitados. "
                "Además podés generar reportes en PDF (generate_report) y consultar "
                "la cola de mensajes pendientes de WhatsApp (get_unanswered_messages). "
                "Usá 'list_models' para ver qué modelos están disponibles. "
                "Usá 'list_reports' para ver qué reportes podés generar. "
                "Los dominios de búsqueda usan formato Odoo: [[\"campo\", \"op\", valor]]. "
                "Para many2one, usá el ID numérico del registro relacionado. "
                "Siempre confirmá con el usuario antes de crear, editar o eliminar registros."
            ),
        }, session_id)

    def _handle_tools_list(self, msg_id, session_id):
        """Return the list of available tools"""
        return self._json_rpc_response(msg_id, {"tools": TOOLS}, session_id)

    def _handle_tools_call(self, msg_id, params, user_env, session_id):
        """Route and execute a tool call"""
        tool_name = params.get('name', '')
        arguments = params.get('arguments', {})

        handler_map = {
            'list_models': self._tool_list_models,
            'get_model_fields': self._tool_get_model_fields,
            'search_records': self._tool_search_records,
            'read_record': self._tool_read_record,
            'create_record': self._tool_create_record,
            'update_record': self._tool_update_record,
            'delete_record': self._tool_delete_record,
            'count_records': self._tool_count_records,
            # New v1.1 tools
            'list_reports': self._tool_list_reports,
            'generate_report': self._tool_generate_report,
            'get_unanswered_messages': self._tool_get_unanswered_messages,
            'mark_message_handled': self._tool_mark_message_handled,
        }

        handler = handler_map.get(tool_name)
        if not handler:
            return self._tool_result(
                msg_id, f"Error: herramienta '{tool_name}' no encontrada.", True)

        try:
            result_text = handler(arguments, user_env)
            return self._tool_result(msg_id, result_text)
        except AccessError as e:
            return self._tool_result(
                msg_id, f"Error de permisos: {e}", True)
        except (ValidationError, UserError) as e:
            return self._tool_result(
                msg_id, f"Error de validación: {e}", True)
        except MissingError as e:
            return self._tool_result(
                msg_id, f"Registro no encontrado: {e}", True)
        except Exception as e:
            _logger.exception("MCP tool error: %s", tool_name)
            return self._tool_result(
                msg_id, f"Error ejecutando {tool_name}: {e}", True)

    # ----------------------------------------------------------
    # Tool Implementations
    # ----------------------------------------------------------

    def _check_model_access(self, model_name, operation='read'):
        """Check if model is enabled and operation is allowed"""
        env = request.env(user=SUPERUSER_ID)
        access = env['mcp.model.access'].get_access_for_model(model_name)
        if not access:
            raise AccessError(
                f"Modelo '{model_name}' no está habilitado para MCP. "
                f"Usá 'list_models' para ver los modelos disponibles."
            )
        perm_map = {
            'read': access.perm_read,
            'create': access.perm_create,
            'write': access.perm_write,
            'unlink': access.perm_unlink,
        }
        if not perm_map.get(operation, False):
            raise AccessError(
                f"Operación '{operation}' no permitida para modelo '{model_name}'."
            )
        return access

    def _filter_fields(self, access, requested_fields, model_obj):
        """Filter fields based on whitelist and requested fields"""
        allowed = access.get_allowed_fields()
        all_model_fields = list(model_obj.fields_get().keys())

        if requested_fields:
            fields_to_use = requested_fields
        else:
            fields_to_use = _smart_fields(model_obj)

        if allowed:
            fields_to_use = [f for f in fields_to_use if f in allowed]

        # Always include 'id'
        if 'id' not in fields_to_use:
            fields_to_use.insert(0, 'id')

        # Filter out fields that don't exist
        fields_to_use = [f for f in fields_to_use if f in all_model_fields or f == 'id']

        return fields_to_use

    def _get_effective_limit(self, access, requested_limit):
        """Get effective record limit"""
        env = request.env(user=SUPERUSER_ID)
        global_max = int(env['ir.config_parameter'].get_param(
            'mcp_server.max_records_global', '200'))
        model_max = access.max_records or global_max

        if requested_limit and requested_limit > 0:
            return min(requested_limit, model_max)
        return min(20, model_max)

    def _tool_list_models(self, args, user_env):
        """List all enabled Odoo models"""
        env = request.env(user=SUPERUSER_ID)
        all_access = env['mcp.model.access'].get_all_enabled_models()
        if not all_access:
            return "No hay modelos habilitados para MCP. Configurá modelos en Ajustes > MCP Server."

        lines = ["Modelos habilitados para MCP:\n"]
        for acc in all_access:
            perms = []
            if acc.perm_read:
                perms.append("leer")
            if acc.perm_create:
                perms.append("crear")
            if acc.perm_write:
                perms.append("editar")
            if acc.perm_unlink:
                perms.append("eliminar")
            model_label = acc.model_id.name if acc.model_id else acc.model_name
            lines.append(
                f"  • {acc.model_name} ({model_label}) "
                f"— Permisos: {', '.join(perms) if perms else 'ninguno'}"
            )
        return "\n".join(lines)

    def _tool_get_model_fields(self, args, user_env):
        """Get field definitions for a model"""
        model_name = args.get('model', '')
        access = self._check_model_access(model_name, 'read')

        model_obj = user_env[model_name]
        fields_info = model_obj.fields_get()
        allowed = access.get_allowed_fields()

        lines = [f"Campos del modelo '{model_name}':\n"]
        count = 0
        for fname, finfo in sorted(fields_info.items()):
            if fname.startswith('__') or fname in ('id',):
                continue
            if allowed and fname not in allowed:
                continue
            ftype = finfo.get('type', '?')
            flabel = finfo.get('string', fname)
            freq = '(requerido)' if finfo.get('required') else ''
            freadonly = '(readonly)' if finfo.get('readonly') else ''
            extra = ''
            if ftype == 'many2one':
                extra = f" → {finfo.get('relation', '?')}"
            elif ftype == 'selection':
                options = finfo.get('selection', [])
                if options:
                    vals = [f"{v[0]}" for v in options[:8]]
                    extra = f" [{', '.join(vals)}]"
            lines.append(
                f"  • {fname} ({ftype}{extra}) — {flabel} {freq} {freadonly}".rstrip()
            )
            count += 1
            if count >= 60:
                remaining = len(fields_info) - count
                lines.append(f"\n  ... y {remaining} campos más. Usá 'fields' en search para pedir campos específicos.")
                break

        return "\n".join(lines)

    def _tool_search_records(self, args, user_env):
        """Search records in an Odoo model"""
        model_name = args.get('model', '')
        domain = args.get('domain', [])
        requested_fields = args.get('fields')
        limit = args.get('limit', 20)
        offset = args.get('offset', 0)
        order = args.get('order')

        access = self._check_model_access(model_name, 'read')
        model_obj = user_env[model_name]
        fields_to_read = self._filter_fields(access, requested_fields, model_obj)
        effective_limit = self._get_effective_limit(access, limit)

        # Parse domain if it's a string
        if isinstance(domain, str):
            try:
                domain = json.loads(domain)
            except json.JSONDecodeError:
                domain = []

        # Search
        search_kwargs = {
            'domain': domain or [],
            'limit': effective_limit,
            'offset': offset or 0,
        }
        if order:
            search_kwargs['order'] = order

        records = model_obj.search_read(
            fields=fields_to_read,
            **search_kwargs,
        )

        total = model_obj.search_count(domain or [])
        formatted = _format_records(records)

        result_lines = [
            f"Resultados para '{model_name}': {len(formatted)} de {total} registros",
            f"Campos: {', '.join(fields_to_read)}\n",
        ]

        for rec in formatted:
            rec_line = f"[ID: {rec.get('id', '?')}]"
            for key, val in rec.items():
                if key == 'id':
                    continue
                if isinstance(val, dict) and 'display' in val:
                    rec_line += f"  {key}: {val['display']} (id={val['id']})"
                elif val is not None:
                    str_val = str(val)
                    if len(str_val) > 100:
                        str_val = str_val[:100] + "..."
                    rec_line += f"  {key}: {str_val}"
            result_lines.append(rec_line)

        if total > len(formatted) + (offset or 0):
            result_lines.append(
                f"\nHay más registros. Usá offset={len(formatted) + (offset or 0)} para la siguiente página."
            )

        return "\n".join(result_lines)

    def _tool_read_record(self, args, user_env):
        """Read a specific record by ID"""
        model_name = args.get('model', '')
        record_id = args.get('record_id')
        requested_fields = args.get('fields')

        if not record_id:
            return "Error: 'record_id' es requerido."

        access = self._check_model_access(model_name, 'read')
        model_obj = user_env[model_name]
        fields_to_read = self._filter_fields(access, requested_fields, model_obj)

        record = model_obj.browse(int(record_id))
        if not record.exists():
            return f"Error: No se encontró registro con ID {record_id} en '{model_name}'."

        data = record.read(fields_to_read)
        if not data:
            return f"Error: No se pudo leer el registro {record_id}."

        formatted = _format_records(data)[0]
        lines = [f"Registro {model_name} [ID: {record_id}]:\n"]
        for key, val in formatted.items():
            if isinstance(val, dict) and 'display' in val:
                lines.append(f"  {key}: {val['display']} (id={val['id']})")
            elif val is not None:
                str_val = str(val)
                if len(str_val) > 500:
                    str_val = str_val[:500] + "..."
                lines.append(f"  {key}: {str_val}")

        return "\n".join(lines)

    def _tool_create_record(self, args, user_env):
        """Create a new record"""
        model_name = args.get('model', '')
        values = args.get('values', {})

        if not values:
            return "Error: 'values' no puede estar vacío."

        access = self._check_model_access(model_name, 'create')
        model_obj = user_env[model_name]

        # Filter values to allowed fields
        allowed = access.get_allowed_fields()
        if allowed:
            filtered_values = {k: v for k, v in values.items() if k in allowed}
            removed = set(values.keys()) - set(filtered_values.keys())
            if removed:
                _logger.warning("MCP create: campos filtrados: %s", removed)
            values = filtered_values

        record = model_obj.create(values)
        display = record.display_name or f"ID {record.id}"

        return (
            f"Registro creado exitosamente:\n"
            f"  Modelo: {model_name}\n"
            f"  ID: {record.id}\n"
            f"  Nombre: {display}\n"
            f"  URL: /web#id={record.id}&model={model_name}&view_type=form"
        )

    def _tool_update_record(self, args, user_env):
        """Update an existing record"""
        model_name = args.get('model', '')
        record_id = args.get('record_id')
        values = args.get('values', {})

        if not record_id:
            return "Error: 'record_id' es requerido."
        if not values:
            return "Error: 'values' no puede estar vacío."

        access = self._check_model_access(model_name, 'write')
        model_obj = user_env[model_name]

        record = model_obj.browse(int(record_id))
        if not record.exists():
            return f"Error: No se encontró registro con ID {record_id} en '{model_name}'."

        # Filter values
        allowed = access.get_allowed_fields()
        if allowed:
            values = {k: v for k, v in values.items() if k in allowed}

        record.write(values)
        display = record.display_name or f"ID {record.id}"

        return (
            f"Registro actualizado exitosamente:\n"
            f"  Modelo: {model_name}\n"
            f"  ID: {record.id}\n"
            f"  Nombre: {display}\n"
            f"  Campos actualizados: {', '.join(values.keys())}"
        )

    def _tool_delete_record(self, args, user_env):
        """Delete a record"""
        model_name = args.get('model', '')
        record_id = args.get('record_id')

        if not record_id:
            return "Error: 'record_id' es requerido."

        access = self._check_model_access(model_name, 'unlink')
        model_obj = user_env[model_name]

        record = model_obj.browse(int(record_id))
        if not record.exists():
            return f"Error: No se encontró registro con ID {record_id} en '{model_name}'."

        display = record.display_name or f"ID {record.id}"
        record.unlink()

        return (
            f"Registro eliminado:\n"
            f"  Modelo: {model_name}\n"
            f"  ID: {record_id}\n"
            f"  Nombre: {display}"
        )

    def _tool_count_records(self, args, user_env):
        """Count records matching a domain"""
        model_name = args.get('model', '')
        domain = args.get('domain', [])

        self._check_model_access(model_name, 'read')
        model_obj = user_env[model_name]

        if isinstance(domain, str):
            try:
                domain = json.loads(domain)
            except json.JSONDecodeError:
                domain = []

        count = model_obj.search_count(domain or [])
        return f"Total de registros en '{model_name}' con el filtro dado: {count}"

    # ----------------------------------------------------------
    # NEW v1.1 Tools
    # ----------------------------------------------------------

    def _tool_list_reports(self, args, user_env):
        """List all enabled Odoo reports"""
        env = request.env(user=SUPERUSER_ID)
        all_reports = env['mcp.report.access'].get_all_enabled_reports()
        if not all_reports:
            return (
                "No hay reportes habilitados para MCP. "
                "Configurá reportes en Ajustes > MCP Server > Reportes habilitados."
            )

        lines = ["Reportes habilitados para MCP:\n"]
        for r in all_reports:
            xml_id = r.report_xml_id or '(sin xml_id)'
            model = r.model_name or '(sin modelo)'
            lines.append(f"  • {r.name}")
            lines.append(f"      xml_id: {xml_id}")
            lines.append(f"      modelo destino: {model}")
            if r.description:
                desc = r.description.strip()[:200]
                lines.append(f"      descripción: {desc}")
            lines.append("")

        return "\n".join(lines)

    def _tool_generate_report(self, args, user_env):
        """Generate a PDF report and store it as ir.attachment"""
        env = request.env(user=SUPERUSER_ID)
        report_xml_id = args.get('report_xml_id', '')
        record_ids = args.get('record_ids', [])
        data = args.get('data') or {}
        filename = args.get('filename')

        if not report_xml_id:
            return "Error: 'report_xml_id' es requerido."
        if not record_ids:
            return "Error: 'record_ids' es requerido y no puede estar vacío."
        if not isinstance(record_ids, list):
            return "Error: 'record_ids' debe ser una lista de IDs."

        # Validar que el reporte esté en la whitelist
        access = env['mcp.report.access'].get_access_for_xml_id(report_xml_id)
        if not access:
            return (
                f"Error: el reporte '{report_xml_id}' no está habilitado para MCP. "
                f"Usá 'list_reports' para ver los reportes disponibles."
            )

        # Aplicar default_data del access si no vino en la llamada
        if access.default_data and not data:
            try:
                data = json.loads(access.default_data)
            except (json.JSONDecodeError, TypeError):
                _logger.warning("MCP: default_data inválido en reporte %s", report_xml_id)

        # Resolver el reporte
        try:
            report = env.ref(report_xml_id)
        except ValueError:
            return f"Error: no se encontró el reporte con xml_id '{report_xml_id}'."

        if report._name != 'ir.actions.report':
            return f"Error: '{report_xml_id}' no es un reporte (es {report._name})."

        # Generar el PDF
        try:
            # Odoo 17/18: _render_qweb_pdf devuelve (bytes, content_type)
            pdf_content, content_type = report._render_qweb_pdf(
                report_xml_id, res_ids=record_ids, data=data
            )
        except Exception as e:
            _logger.exception("MCP: error generando reporte %s", report_xml_id)
            return f"Error generando el reporte: {e}"

        # Crear ir.attachment
        if not filename:
            safe_name = (report.name or 'reporte').replace('/', '_').replace(' ', '_')
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{safe_name}_{ts}.pdf"
        elif not filename.lower().endswith('.pdf'):
            filename = f"{filename}.pdf"

        attachment_vals = {
            'name': filename,
            'datas': base64.b64encode(pdf_content),
            'mimetype': 'application/pdf',
            'type': 'binary',
            'description': f"Generado via MCP — Reporte: {report.name} — Records: {record_ids}",
        }

        attachment = env['ir.attachment'].create(attachment_vals)

        size_kb = len(pdf_content) / 1024.0

        return (
            f"PDF generado exitosamente:\n"
            f"  Reporte: {report.name}\n"
            f"  Archivo: {filename}\n"
            f"  Tamaño: {size_kb:.1f} KB\n"
            f"  Attachment ID: {attachment.id}\n"
            f"  Records incluidos: {len(record_ids)} ({record_ids})\n"
            f"\n"
            f"Para enviar este PDF como adjunto en un mensaje de WhatsApp, "
            f"creá un mail.message con attachment_ids=[[4, {attachment.id}]] "
            f"y luego un whatsapp.message vinculado a ese mail.message."
        )

    def _tool_get_unanswered_messages(self, args, user_env):
        """Return WhatsApp channels with unanswered inbound messages"""
        env = request.env(user=SUPERUSER_ID)
        limit = args.get('limit', 20) or 20
        include_in_progress = bool(args.get('include_in_progress', False))

        states = ['pending']
        if include_in_progress:
            states.append('in_progress')

        # Refrescar la cola antes de leer (por si el cron no corrió recién)
        try:
            env['mcp.pending.message']._refresh_queue()
        except Exception:
            _logger.exception("MCP: error refrescando cola antes de get_unanswered_messages")

        pendings = env['mcp.pending.message'].search([
            ('state', 'in', states),
        ], order='last_inbound_at desc', limit=limit)

        if not pendings:
            return "No hay mensajes pendientes de respuesta."

        lines = [
            f"Mensajes pendientes de respuesta ({len(pendings)} canales):\n",
        ]
        for p in pendings:
            partner_label = p.partner_id.display_name if p.partner_id else "(sin partner)"
            channel_label = p.channel_id.name if p.channel_id else "(sin canal)"
            account_label = p.wa_account_id.name if p.wa_account_id else "?"
            mobile = p.mobile_number or "?"
            received = (p.last_inbound_at.strftime('%Y-%m-%d %H:%M:%S')
                        if p.last_inbound_at else "?")
            summary = (p.summary or "").strip().replace('\n', ' ')[:200]
            extra = ""
            if p.inbound_count and p.inbound_count > 1:
                extra = f" (+{p.inbound_count - 1} mensajes seguidos)"

            lines.append(
                f"  • [Pending #{p.id}] Canal {p.channel_id.id} ({channel_label})\n"
                f"      Estado: {p.state}{extra}\n"
                f"      Cuenta WA: {account_label}\n"
                f"      Contacto: {partner_label} ({mobile})\n"
                f"      Recibido: {received}\n"
                f"      Mensaje: {summary}\n"
                f"      Último mail.message ID: {p.last_inbound_message_id.id if p.last_inbound_message_id else '?'}\n"
            )

        lines.append(
            "\nDespués de responder a un canal, llamá mark_message_handled "
            "con el channel_id para sacarlo de la cola."
        )
        return "\n".join(lines)

    def _tool_mark_message_handled(self, args, user_env):
        """Mark a channel's pending entry as handled"""
        env = request.env(user=SUPERUSER_ID)
        channel_id = args.get('channel_id')
        state = args.get('state', 'done')

        if not channel_id:
            return "Error: 'channel_id' es requerido."
        if state not in ('done', 'ignored', 'in_progress', 'pending'):
            return f"Error: estado '{state}' inválido. Usá done, ignored, in_progress o pending."

        pending = env['mcp.pending.message'].search([
            ('channel_id', '=', int(channel_id)),
        ], limit=1)

        if not pending:
            return (
                f"No hay entrada en la cola de mensajes pendientes para el canal {channel_id}. "
                f"Esto puede pasar si nunca hubo un mensaje entrante en ese canal "
                f"o si el cron todavía no lo registró."
            )

        pending.write({
            'state': state,
            'processed_at': fields.Datetime.now(),
        })
        return (
            f"Canal {channel_id} marcado como '{state}'. "
            f"Pending entry ID: {pending.id}."
        )
