# Cristal Agent — Claudio

Agente comercial autónomo para **Química Cristal** (Río Cuarto, Argentina), desarrollado sobre **Odoo 18** y **Claude (Anthropic)**.

Atiende clientes Mayoristas vía WhatsApp Business como un empleado real:
- Saluda, califica, manda muestras, hace seguimientos, cierra ventas.
- Aprende del negocio. Joaco le habla en un canal interno y Claudio guarda el conocimiento.
- Escala automáticamente cuando algo necesita atención humana.
- Lleva el CRM (crm.lead) actualizado por sí solo.
- Maneja niveles BRONCE/PLATA/ORO con cron mensual.
- Detecta clientes en riesgo de churn y activa flujos de recuperación.

---

## Cómo funciona

```
Cliente WA  ──▶  whatsapp.message  ──▶  hook detecta mensaje entrante
                                              │
                                              ▼
                              cristal.agent.run (audit log)
                                              │
                                              ▼
                                    services/claude_client.py
                                    (loop de tool_use)
                                              │
                              ┌───────────────┼───────────────┐
                              ▼               ▼               ▼
                        Anthropic API   ToolRegistry   cristal.agent.knowledge
                        (Claude API)    (25+ tools)    (KB editable)
                              │
                              ▼
                    send_whatsapp tool
                              │
                              ▼
                    whatsapp.message._send_message()
                    (envío instantáneo)
                              │
                              ▼
                          Cliente
```

---

## Componentes principales

### Modelos
- `cristal.agent.config` — configuración global (API key, modelo, system prompt, identidades)
- `cristal.agent.run` — log auditable de cada ejecución (con tokens, costo, tool calls)
- `cristal.agent.memory` — memoria por cliente (estado del flujo, takeover, calificación)
- `cristal.agent.knowledge` — base de conocimiento dinámica (editable, expira, prioridad)
- `cristal.agent.offer` — ofertas comerciales activas (que el bot menciona)

Extensiones de modelos existentes:
- `res.partner` — agrega `agent_level`, `agent_strategy_phase`, `agent_observations`, `agent_churn_score` y otros
- `crm.lead` — agrega `agent_managed`, `agent_strategy_phase`, datos de qualificación
- `whatsapp.message` — hook para detectar mensajes entrantes y disparar el agente
- `mail.message` — hook para detectar intervención humana y comandos `/on` `/off`

### Tools del agente (25)
**Mensajería:** `send_whatsapp`, `escalate_to_joaco`, `view_attachment`, `read_message_history`

**Partners:** `search_partners`, `read_partner`, `create_partner`, `update_partner`, `update_observation`

**CRM:** `create_lead`, `update_lead`, `schedule_activity`, `mark_activity_done`

**Conocimiento:** `search_knowledge`, `add_knowledge`, `search_offers`

**Productos:** `search_products`, `check_stock`

**Órdenes / Facturas:** `search_orders`, `search_invoices`

**PDFs:** `generate_quote_pdf`, `generate_pricelist_pdf`

**Niveles:** `compute_partner_level`, `set_partner_level`

**Operativos:** `pause_bot`

---

## Instalación

Ver `INSTALL.md`.

## Configuración

Ver `INSTALL.md`.

## Crons

Por defecto, los crons "comerciales" (cadencias, niveles, churn) están **desactivados**. Activalos manualmente desde **Configuración → Tareas Programadas** uno por uno cuando estés listo.

Crons activos por default (técnicos):
- Reactivar takeovers expirados (cada 10 min)
- Desactivar conocimiento vencido (diario)
- Desactivar ofertas vencidas (diario)

---

## Costos esperados

Con prompt caching habilitado y volumen razonable (~100-200 mensajes/día):
- Sin caching: ~$15-30 USD/mes
- Con caching: ~$3-8 USD/mes

Cada ejecución se loguea en `cristal.agent.run` con el costo en USD.

---

## Versión

`18.0.1.0.0` (mayo 2026)

## Licencia

LGPL-3
