# MCP Server para Odoo 18

Módulo que convierte tu instancia de Odoo en un servidor MCP (Model Context Protocol),
permitiendo que asistentes de IA como Claude interactúen con tus datos de negocio
a través de lenguaje natural.

## Novedades v1.1

- **Tool `generate_report`** — generar PDFs de reportes (lista de precios, presupuestos, facturas) y guardarlos como adjuntos para enviar por WhatsApp/Email.
- **Tool `list_reports`** — listar reportes habilitados.
- **Tool `get_unanswered_messages`** — leer la cola de mensajes pendientes de respuesta en WhatsApp.
- **Tool `mark_message_handled`** — marcar conversaciones como atendidas.
- **Cron automático** que mantiene actualizada la cola de mensajes pendientes (cada 2 min).
- **+15 modelos nuevos habilitados** por defecto: `ir.attachment`, `ir.model`, `mail.activity.type`, `discuss.channel.member`, `product.tag`, `whatsapp.message`, etc.
- **Whitelist de reportes** (`mcp.report.access`) — solo los reportes registrados pueden ejecutarse via MCP.

## Instalación en Odoo SH

### 1. Subir el módulo

```bash
# En tu repositorio de Odoo SH, copiar la carpeta mcp_server/
# a tu directorio de addons custom (típicamente la raíz del repo)
git add mcp_server/
git commit -m "feat(mcp_server): v1.1 - reportes, cola de mensajes, modelos extra"
git push
```

### 2. Actualizar el módulo

- Ir a **Apps** en Odoo
- Buscar "MCP Server"
- Click en **Actualizar** (no reinstalar)

Si ya estaba instalado en una versión anterior, la actualización corre automáticamente
las migraciones de los nuevos modelos y datos.

### 3. Configurar (si es instalación nueva)

#### Crear API Key:
1. Ir a **MCP Server → Configuración → API Keys**
2. Click en **Nuevo**
3. Darle un nombre (ej: "Claude AI")
4. Seleccionar el usuario Odoo cuyos permisos se usarán (ej: usuario "Claudio")
5. Guardar → se genera automáticamente una API key
6. Copiar la URL que aparece en el formulario

#### Reportes habilitados (vienen pre-cargados):
1. Ir a **MCP Server → Configuración → Reportes habilitados**
2. Verás 3 reportes pre-cargados: Lista de precios, Presupuesto, Factura
3. Podés agregar más reportes a la whitelist según necesidad

### 4. Conectar con Claude.ai

1. Ir a [claude.ai/settings/connectors](https://claude.ai/settings/connectors)
2. Click en **Add custom connector**
3. Pegar la URL: `https://quimicacristal.odoo.com/mcp/TU_API_KEY`
4. Click en **Add**
5. En un chat nuevo, activar el conector desde el botón "+" → Connectors

## Herramientas disponibles (Tools)

### CRUD básico

| Tool | Descripción |
|------|-------------|
| `list_models` | Lista modelos habilitados con sus permisos |
| `get_model_fields` | Muestra campos de un modelo |
| `search_records` | Busca registros con filtros |
| `read_record` | Lee un registro por ID |
| `create_record` | Crea un nuevo registro |
| `update_record` | Actualiza un registro existente |
| `delete_record` | Elimina un registro |
| `count_records` | Cuenta registros con filtros |

### Nuevas en v1.1

| Tool | Descripción |
|------|-------------|
| `list_reports` | Lista reportes permitidos para ejecutar |
| `generate_report` | Genera un PDF de reporte y lo guarda como `ir.attachment` |
| `get_unanswered_messages` | Devuelve canales de WhatsApp con mensajes pendientes de respuesta |
| `mark_message_handled` | Marca una conversación como atendida en la cola |

### Ejemplo de generación de PDF

```python
# Claude llama:
generate_report(
    report_xml_id="product.action_report_pricelist",
    record_ids=[7862, 7864, 7865],  # IDs de product.template
    data={"pricelist_id": 6, "quantities": [1]}
)
# Devuelve: attachment_id: 12345

# Luego Claude crea el mail.message con el adjunto:
create_record(
    model="mail.message",
    values={
        "author_id": 80799,  # Claudio
        "body": "<p>Acá te paso la lista de precios mayorista.</p>",
        "message_type": "whatsapp_message",
        "model": "discuss.channel",
        "res_id": 627,
        "subtype_id": 1,
        "attachment_ids": [[4, 12345]]
    }
)
```

## Modelos pre-configurados

### Negocio
- **res.partner** (Contactos) — CRUD sin eliminar
- **product.template** (Productos) — CRUD sin eliminar
- **product.product** (Variantes) — Lectura + edición
- **product.category** — CRUD sin eliminar
- **product.tag** — Solo lectura *(nuevo v1.1)*
- **product.pricelist** — Solo lectura
- **sale.order** — CRUD sin eliminar
- **sale.order.line** — CRUD completo
- **crm.lead** — CRUD sin eliminar
- **account.move** (Facturas) — Solo lectura
- **stock.quant** — Solo lectura

### Mensajería *(nuevo v1.1)*
- **mail.message** — Lectura + creación
- **mail.activity** — Lectura + creación + edición
- **mail.activity.type** — Solo lectura
- **discuss.channel** — CRUD sin eliminar
- **discuss.channel.member** — CRUD completo

### WhatsApp *(nuevo v1.1)*
- **whatsapp.message** — CRUD sin eliminar
- **whatsapp.template** — CRUD sin eliminar
- **whatsapp.account** — Solo lectura

### Técnicos *(nuevo v1.1)*
- **ir.model** — Solo lectura (resolver `res_model_id` por nombre técnico)
- **ir.actions.report** — Solo lectura (listar reportes disponibles)
- **ir.attachment** — Lectura + creación + edición (con whitelist de campos)

### Auxiliares *(nuevo v1.1)*
- **crm.team**, **crm.stage**, **crm.tag** — Lectura
- **res.partner.category** — Lectura + edición
- **res.country**, **res.country.state** — Solo lectura
- **res.users** — Solo lectura

## Cola de mensajes pendientes

El cron `MCP: Refrescar cola de mensajes pendientes` corre cada 2 minutos y mantiene
la tabla `mcp.pending.message` actualizada con:

- Canales de WhatsApp con mensajes entrantes sin respuesta posterior
- Estado: `pending`, `in_progress`, `done`, `ignored`

Podés ver la cola desde **MCP Server → Mensajes pendientes** en la UI de Odoo, o consultarla
desde Claude con la tool `get_unanswered_messages`.

### Configuración del cron

- **Frecuencia:** cada 2 minutos (modificable desde *Ajustes → Técnico → Acciones planificadas*)
- **Ventana de búsqueda:** 30 días hacia atrás (configurable vía parámetro `mcp_server.pending_lookback_days`)

## Seguridad

- Autenticación por API key en URL o Bearer token
- Permisos granulares por modelo (CRUD)
- Whitelist de campos opcional por modelo
- **Whitelist de reportes** (`mcp.report.access`) — los reportes deben registrarse explícitamente para poder ejecutarse
- Límites de registros por consulta
- Log de todas las solicitudes
- Las operaciones respetan los permisos del usuario Odoo asociado a la API key

## Endpoints

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/mcp/<token>` | POST | Endpoint principal MCP |
| `/mcp/<token>` | GET | Health check |
| `/mcp/<token>` | DELETE | Cerrar sesión |
| `/mcp` | POST | Con Bearer token en header |

## Tip: bajar el delay de mensajes salientes de WhatsApp

El módulo `whatsapp` de Odoo tiene su propio cron para despachar mensajes `outgoing`.
Si notás que los mensajes que crea Claude tardan 1-2 minutos en salir, podés bajarle
la frecuencia desde *Ajustes → Técnico → Acciones planificadas → "WhatsApp: Send queued messages"*
(o nombre similar) y ponerlo cada 30 segundos.
