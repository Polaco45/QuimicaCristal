# Guía de instalación — Cristal Agent

## Pre-requisitos

- Odoo 18 (Online o SH)
- El módulo `whatsapp` de Odoo instalado y configurado con al menos una WhatsApp Business Account
- API key de Anthropic ([https://console.anthropic.com/](https://console.anthropic.com/) → Settings → API Keys)
- El módulo viejo `chatbot_whatsapp` desinstalado (si lo tenías). El nuevo módulo lo reemplaza completamente.

---

## Instalación en Odoo SH

1. **Subir el módulo**

   Subí la carpeta `cristal_agent/` a tu repo de Odoo SH (en la rama `staging` primero, después en `production`).

   Estructura esperada:
   ```
   tu_repo/
   └── cristal_agent/
       ├── __manifest__.py
       ├── __init__.py
       ├── models/
       ├── services/
       ├── data/
       ├── views/
       ├── controllers/
       └── ...
   ```

2. **Esperar el build**

   Odoo SH va a hacer el build automáticamente. Mirá los logs por si hay algún error.

3. **Instalar el módulo**

   - Apps → Quitar el filtro "Apps" → Buscar "Cristal Agent"
   - Click en **Instalar**

   Al instalar:
   - Se crea la `cristal.agent.config` con defaults
   - Se carga el system prompt Claudio v2 desde `data/prompts/claudio_v2.md`
   - Se crean ~13 entries de conocimiento inicial en la KB
   - Se crean los crons (los técnicos activos, los comerciales desactivados)

---

## Configuración (después de instalar)

### 1. Configurar API key de Anthropic

- Andá a `🤖 Cristal Agent → Configuración → ⚙️ Configuración`
- Abrí "Configuración principal"
- Pegá tu API key en el campo **Anthropic API Key**
- Guardá

### 2. Test de conexión

- En la misma pantalla, hacé click en **🔌 Test de conexión Anthropic**
- Debería responder "Claude respondió: OK" (o similar)
- Si falla, verificá: API key correcta, modelo `claude-sonnet-4-6` disponible en tu cuenta de Anthropic

### 3. Verificar identidades técnicas

En la pestaña **👥 Identidades técnicas** verificá que los IDs corresponden a tu instancia:

- `bot_partner_id`: 80799 (claudio.quimicacristal)
- `owner_partner_id`: 65374 (Joaquín)
- `owner_user_id`: 18 (Joaquín como user)
- `bot_user_id`: 721 (claudio como user)
- `internal_channel_id`: 969 (canal interno Joaco↔Claudio)

Si alguno cambió (por restore, nueva instancia, etc.), corregilo.

### 4. Test inicial de respuesta

Mandate un mensaje de WhatsApp desde tu propio número al número de Cristal:
> "Hola"

Deberías recibir respuesta del bot en menos de 30 segundos.

Andá a `🤖 Cristal Agent → Operativa → 📜 Ejecuciones` y deberías ver el run.

---

## Activar los crons comerciales (cuando estés listo)

Los crons están **desactivados por defecto** para que primero pruebes el bot solo respondiendo mensajes.

Cuando estés cómodo con cómo responde, activá los crons uno por uno:

1. **Configuración → Técnico → Tareas Programadas** (o `/odoo/action-base.action_ir_cron_act`)
2. Buscá los que empiezan con "Cristal Agent:"
3. Activalos uno por uno, mirando el log de ejecuciones después de cada activación.

Orden recomendado:
1. **Recálculo mensual de niveles** (tarda 1 mes en disparar de todas formas)
2. **Detección de churn diario** (riesgo bajo)
3. **Cadencia Fase 2** (cuando ya tengas leads en fase 2)
4. **Cadencia Fase 3** (cuando ya tengas onboardings activos)

---

## Cargar ofertas activas

Antes de empezar a operar, cargá las ofertas vigentes en `🎁 Ofertas activas`:

Ejemplo:
- **Nombre**: "Octubre 2026 — 10% off limpiavidrios 5L"
- **Tipo**: % de descuento
- **Discount %**: 10
- **Vigente desde**: 2026-10-01
- **Vigente hasta**: 2026-10-31
- **Aplica a niveles**: Todos
- **Descripción**: "Esta semana 10% off en limpiavidrios formato 5L para todos los Mayoristas."
- **Comunicación proactiva**: ON (si querés que el bot los proponga sin que el cliente pregunte)

---

## Cargar conocimiento adicional

A medida que opera, vas a querer agregar conocimiento. Hay 3 formas:

**1. Manual** desde `📚 Base de conocimiento → Crear`

**2. Hablándole a Claudio en el canal interno (id 969)**

   Ejemplo: si en el canal le decís a Claudio:
   > "Anotate que a partir de ahora los pagos en efectivo tienen 5% extra"

   Claudio detecta la enseñanza y crea automáticamente la entry en la KB con `source = "Aprendido en chat con Joaco"`.

**3. El bot mismo, a partir de observaciones automáticas**

   Si detecta un patrón importante en un cliente, puede crear una entry tipo `observacion_cliente`.

---

## Apagar el bot temporalmente

Si necesitás que el bot deje de responder a TODOS los clientes:
- Configuración → Configuración principal → Desmarcar **"Agente habilitado"**

Si necesitás pausar el bot solo para UN cliente puntual:
- En el canal de WhatsApp con ese cliente, escribí `/off` (mensaje interno)
- Para reactivar, escribí `/on`
- O escribí cualquier mensaje normal en el canal: el bot detecta intervención humana y se pausa 1 hora automáticamente

---

## Troubleshooting

**El bot no responde a mensajes WA**

1. Verificar que la API key esté configurada y el test de conexión funcione.
2. Verificar que el agente esté habilitado (Configuración → Agente habilitado = ON).
3. Verificar el log: `🤖 Cristal Agent → Ejecuciones` (filtro "Hoy", filtro "Con error").
4. Verificar el log de Odoo SH (logs estándar de Odoo). Buscar líneas con `🚀 Disparando agente`.

**El bot responde pero la API tira error**

1. Mirá la ejecución específica en `Ejecuciones`.
2. Pestaña "Error" muestra el detalle.
3. Causas comunes:
   - API key inválida o sin saldo → ver Anthropic Console.
   - Modelo `claude-sonnet-4-6` no disponible en tu cuenta → cambiar a `claude-sonnet-4-5` u otro disponible.
   - Timeout → la conversación tomó demasiado, mirá si hay loops.

**El bot manda mensaje pero el cliente no lo recibe**

1. Verificar que `wa_account_id` en el run coincida con la cuenta WA correcta.
2. Verificar que el cliente no tenga el número bloqueado.
3. Verificar status del whatsapp.message generado (deberia estar `sent` y luego `delivered`).

---

## Soporte

Issues → reportar a Joaquín.
