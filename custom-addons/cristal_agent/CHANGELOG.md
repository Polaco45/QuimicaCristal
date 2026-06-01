# CHANGELOG — Cristal Agent

Todas las novedades del módulo se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) y el módulo
adhiere a [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [18.0.1.10.0] — 2026-06-01

### Flow institucional v2 — triage de intención + orden nuevo

El número de Química Cristal (Compras) recibe de todo, no solo leads. Antes el bot
disparaba el pitch de Plan Control ante cualquier mensaje no-bypasseado (incluido un
"gracias"). Esta versión agrega clasificación de intención y reordena el flujo.

#### Added
- `data/prompts/claudio_institutional_v2.md`: nuevo prompt institucional con
  **STEP 0 TRIAGE** (A: lead interesado → corre flujo; B: consulta operativa →
  línea de espera + `escalate_to_joaco` + `pause_bot(0)`; C: ruido/social/equivocado
  → no responde) y el orden nuevo: nombre+empresa → `create_lead` (opp temprana,
  idempotente) → propuesta + reporte de muestra adjunto + CTA de visita → si SÍ,
  calificación completa con chequeo de zona → `complete_institutional_qualification`.
- Campo `institutional_report_attachment_id` en `cristal.agent.config`: PDF de
  muestra del reporte mensual que el bot adjunta en la propuesta.
- `prompt_builder` inyecta el ID del reporte en el placeholder
  `{{REPORTE_MUESTRA_ATTACHMENT_ID}}`. Si no está configurado, el bot manda la
  propuesta sin adjunto y avisa a Joaco.
- Campo del reporte agregado a la vista de config (tab Institucional).
- `migrations/18.0.1.10.0/post-migration.py`: carga el prompt v2 en la config.

#### Notes
- NO cambia el ruteo institucional/mayorista (por cuenta WA) ni el bypass de
  cliente activo: siguen igual.
- Manual post-deploy: subir `reporte_muestra.pdf` como adjunto y seleccionarlo en
  Config → Institucional → "Reporte de muestra". Sin eso, la propuesta sale sin PDF.
- Pendiente para que la opp temprana no ensucie el pipeline: prender una cadencia
  de seguimiento sobre la etapa "Propuesta enviada".

---

## [18.0.1.0.0] — 2026-05-08

### Versión inicial

#### Características principales
- Motor del agente con loop de tool_use propio (sin MCP-via-API).
- Cliente de Claude API con prompt caching (anthropic-version 2023-06-01).
- 25 tools que cubren mensajería WA, partners, CRM, KB, productos, niveles y operativos.
- System prompt Claudio v2 (~406 líneas) que define personalidad, las 5 fases comerciales y las reglas operativas.
- Modelo de auditoría (cristal.agent.run) con tracking de tokens, costo USD y duración.
- Modelo de memoria por cliente (cristal.agent.memory) con buffer de calificación, takeover humano, comandos `/on` `/off`.
- Modelo de KB editable (cristal.agent.knowledge) con prioridad, vigencia, targeting por nivel/cliente.
- Modelo de ofertas (cristal.agent.offer) que el bot consulta al hablar con clientes.
- Extensión de res.partner con campos del agente: nivel, fase comercial, observaciones acumuladas, churn score.
- Extensión de crm.lead con fase comercial y datos de calificación.
- Hook en whatsapp.message: detecta mensajes entrantes y dispara el agente.
- Hook en mail.message: detecta intervención humana, comandos `/on` `/off`, takeover automático.
- Tool `send_whatsapp` con envío INSTANTÁNEO usando `_send_message()` del módulo whatsapp (sin esperar cron).
- Crons:
  - Reactivar takeovers expirados (10 min) — activo
  - Desactivar conocimiento vencido (diario) — activo
  - Desactivar ofertas vencidas (diario) — activo
  - Cadencia Fase 2 (post-muestra) — DESACTIVADO por default
  - Cadencia Fase 3 (onboarding 1ra compra) — DESACTIVADO
  - Recálculo mensual de niveles — DESACTIVADO
  - Detección de churn diario — DESACTIVADO
- Conocimiento inicial: ~13 entries con políticas comerciales, escalación, niveles, calificación.
- Vistas: Dashboard, Ejecuciones, Memorias, KB, Ofertas, Configuración. Pestaña "🤖 Agente Claudio" en partners.
- Endpoints HTTP: health check, test_simulate.

#### Limitaciones conocidas
- Visión multimodal (imágenes) preparada pero no aplicada al loop principal — viene en V2.
- Audio del cliente no se procesa: el bot escala automáticamente.
- Las cadencias proactivas (crons) están desactivadas por seguridad: activación manual.
- Solo opera con clientes Mayoristas. CF y Empresa: respuesta simple + escalación.

#### Próximas versiones
- v18.0.2.0.0 — Visión multimodal completa, calificación Fase 1 con preguntas estructuradas.
- v18.0.3.0.0 — Soporte de audios (transcripción → procesamiento).
- v18.0.4.0.0 — Dashboard de KPIs avanzado, reports semanales.
