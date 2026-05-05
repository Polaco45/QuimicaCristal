# MCP Server para Odoo 18

Módulo que convierte tu instancia de Odoo en un servidor MCP (Model Context Protocol),
permitiendo que asistentes de IA como Claude interactúen con tus datos de negocio
a través de lenguaje natural.

## Instalación en Odoo SH

### 1. Subir el módulo

```bash
# En tu repositorio de Odoo SH, copiar la carpeta mcp_server/
# a tu directorio de addons custom (típicamente la raíz del repo)
git add mcp_server/
git commit -m "feat: add MCP Server module"
git push
```

### 2. Instalar el módulo

- Ir a **Apps** en Odoo
- Hacer click en **Actualizar lista de apps**
- Buscar "MCP Server"
- Click en **Instalar**

### 3. Configurar

#### Crear API Key:
1. Ir a **MCP Server → Configuración → API Keys**
2. Click en **Nuevo**
3. Darle un nombre (ej: "Claude AI")
4. Seleccionar el usuario Odoo cuyos permisos se usarán
5. Guardar → se genera automáticamente una API key
6. Copiar la URL que aparece en el formulario

#### Configurar modelos (ya vienen pre-cargados):
1. Ir a **MCP Server → Configuración → Modelos Habilitados**
2. Ajustar permisos CRUD según necesidad
3. Opcionalmente limitar campos con la whitelist

### 4. Conectar con Claude.ai

1. Ir a [claude.ai/settings/connectors](https://claude.ai/settings/connectors)
2. Click en **Add custom connector**
3. Pegar la URL: `https://quimicacristal.odoo.com/mcp/TU_API_KEY`
4. Click en **Add**
5. En un chat nuevo, activar el conector desde el botón "+" → Connectors

## Herramientas disponibles (Tools)

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

## Modelos pre-configurados

- **res.partner** (Contactos) — CRUD sin eliminar
- **product.template** (Productos) — CRUD sin eliminar
- **sale.order** (Pedidos de venta) — CRUD sin eliminar
- **sale.order.line** (Líneas de pedido) — CRUD completo
- **crm.lead** (CRM Leads) — CRUD sin eliminar
- **account.move** (Facturas) — Solo lectura
- **stock.quant** (Stock) — Solo lectura
- **product.pricelist** (Listas de precios) — Solo lectura

## Seguridad

- Autenticación por API key en URL o Bearer token
- Permisos granulares por modelo (CRUD)
- Whitelist de campos opcional
- Límites de registros por consulta
- Log de todas las solicitudes
- Las operaciones respetan los permisos del usuario Odoo asociado

## Endpoints

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/mcp/<token>` | POST | Endpoint principal MCP |
| `/mcp/<token>` | GET | Health check |
| `/mcp/<token>` | DELETE | Cerrar sesión |
| `/mcp` | POST | Con Bearer token en header |
