# Plan — Cupones de eventos HISPANO15 y OUTLON15 (cristal_agent 1.82.0)

> **Cambio 1.82.3:** el código de CIMA Oulton es **OULTON15** (regla 101 del programa 92); OUTLON15 queda como variante reconocida.
>
> **Cambio 1.82.1 (Joaco, 26/11/2026): "no campaña aparte".** No hay mensajes proactivos: las cadencias A-E quedan apagadas (`cristal_agent.event_coupon_followups = 0`), las plantillas `cupon_evento_*` quedan archivadas sin enviar a Meta y el cron solo mide compras. Claudio atiende a quien escribe con el código como consumidor final y le ofrece productos para la casa. Se mantienen el registro del día 0, los controles al enviar y la medición. OULTON15 se reconoce como OUTLON15. Las secciones 2 y 4 de abajo (pasos A-E) quedan solo como referencia.

Fuente: `Cadencia_Claudio_Cupones_Eventos.md` (Joaco, 26/11/2026). Número de Claudio 3586091684 = cuenta de WhatsApp **Cristal Mayorista (id 8)**.

## Datos verificados en producción (26/11/2026)

| | HISPANO15 | OUTLON15 |
|---|---|---|
| Programa / regla / recompensa | 91 / 100 / 138 | 92 / 101 / 139 |
| Producto de la línea de descuento | 12485 | 12486 |
| Mínimo | $20.000 IVA incluido | igual |
| Web / POS | web 1 + todos los POS (San Martín, San Martín 2) | igual |
| Usos hasta hoy | 0 | 0 |
| Mercadería regalada (costo) | S07503 (Sociedad Española): **$29.608** | S07502 (CIMA Oulton): **$11.831** |

- No existe un equipo de ventas "Consumidor final": los que hay son Sales, Website, Cristal Mayorista, Institucional, POS y Compras Públicas.
- Las plantillas A, B y C no existen. Ya aprobadas en la cuenta 8 y útiles para D y E: **259 `cristal_satisfaccion`** (utilidad, "¿cómo te fue con tu compra del {{2}}?", con botones) y **258 `cristal_reposicion`** (marketing, "se te estaría terminando {{2}}…").
- La regla 132 (KB) hoy pide a Claudio que anote el origen en observaciones y que escale los pedidos con envío. Eso queda: lo que cambia es que el registro lo hace el código y el seguimiento también.
- El 24/01/2027 es **domingo**.

## Arquitectura

**Modelo nuevo `cristal.agent.event`** (uno por evento, cargado por la migración):
código, nombre, programa de fidelidad, palabras clave (Sociedad Española / RMI, CIMA, Oulton), etiqueta de contacto, etiqueta CRM, lista de correo, pedido de la mercadería regalada, fecha de fin (31/01/2027) y los indicadores calculados (ver Medición).

**Modelo nuevo `cristal.agent.event.contact`** (uno por persona y evento):
partner, evento, fecha de entrada, lead, estado (`active` siguiendo / `purchased` compró / `wholesale` mayorista / `opted_out` baja / `finished` terminó sin comprar / `done` terminó post-compra), fecha y paso de cada mensaje A–E, fecha de la compra, pedido web o POS, importe sin IVA y en qué paso estaba cuando compró.

**Cadencias:** `trigger_event` suma `event_coupon` ("Cupón de evento") y `event_coupon_purchase` ("Compra con cupón de evento"). La migración crea 5 registros `cristal.agent.cadence` (A, B, C, D, E) con días, plantilla y guía de variables, editables desde la pantalla de cadencias. Hay un campo nuevo `step_code` (A–E). El cron lee ahí la plantilla: si la plantilla no está aprobada, el paso no sale y queda registrado el motivo "plantilla no aprobada".

## Flujos

### 1. Entrada (día 0), en el webhook, sin llamar a la IA
- **Disparador:** el texto trae `HISPANO15` u `OUTLON15` (sin importar mayúsculas ni espacios), o "cupón" junto con alguna palabra clave del evento. Solo por la cuenta 8 y solo mientras el evento está vigente.
- **Registro inmediato (código):** partner por celular (el que ya busca o crea el webhook), etiqueta `Evento <código>`, `crm.lead` "Cupón evento – <código> – <nombre>" (equipo **Website**, vendedor OdooBot, nunca Joaco, etiqueta CRM `Evento <código>`, origen = código), alta en la lista "Evento <código>" y `agent_origin_code` = código. Si la persona ya está registrada en ese evento, no se duplica nada.
- **Respuesta:** la da Claudio en la misma corrida de siempre. `prompt_builder` le agrega un bloque **"🎟️ CUPÓN DE EVENTO"** con el texto exacto del documento (código correcto), le indica pedir el nombre solo si todavía no se le pidió y solo si el nombre es el genérico "WhatsApp: …", y le aclara que el seguimiento lo hace el sistema.
- **Control al enviar (`send_guards`):** si el cliente pidió el cupón hoy y el mensaje no nombra el código, no sale. Así se evita que la IA conteste sin el cupón o con otro código. Si es la segunda vez que falla, se manda el texto fijo.
- **Nombre:** cuando Claudio guarda el nombre (`update_partner`), el lead se renombra solo y queda marcado como "nombre pedido".
- **Mayorista o revendedor:** si el mensaje dice "revendo", "mayorista", "negocio", "comercio", etc., o si el partner ya es comprador mayorista, el contacto queda `wholesale`: recibe el cupón, sigue el flujo mayorista normal y no entra en esta cadencia.
- **Motor mayorista (NBA):** `_blocked_reason` agrega "en circuito de cupón de evento" para que no le mande al mismo contacto las preguntas de calificación mayorista (l_pregunta del día 3).
- **Después del 31/01/2027:** el evento vence. Claudio responde que el cupón venció y lo deriva a la web o al local, como cualquier consumidor final.

### 2. Seguimiento A, B y C (cron `cron_event_coupons`, cada hora)
- **Solo de lunes a viernes, entre las 10 y las 19 (hora AR), y nunca en feriado ni día cerrado** (`closed_day_reason`).
- **Fechas:** A = entrada + 3; B = entrada + 10; C = lunes **25/01/2027** (el 24/01 cae domingo) si entró hasta el 30/12, y si entró después, entrada + 25 con tope el viernes 29/01. Los pasos A o B que caerían en la fecha de C o después no se mandan. Si un paso cae en fin de semana, sale el lunes.
- **Antes de cada paso se corta si:**
  - el cupón ya se usó (`sale.order` confirmado con una línea de la recompensa 138/139, o `pos.order` pagado con esa línea, del partner o de su empresa);
  - hay "No contactar" (opt-out);
  - hay intervención humana;
  - ya recibió 3 mensajes proactivos.
- **Ventana de 24 h abierta** (el cliente está hablando con Claudio): el paso se posterga al día siguiente. No se paga una plantilla y no se le mete un recordatorio en medio de la charla.
- **Envío:** por el mismo camino que la tool `send_whatsapp_template` (composer con `from_cristal_agent`, política de plantillas: 72 h entre comerciales, 2 por semana, no en día cerrado). Si la política lo bloquea, se reintenta el próximo día hábil, y si se pasa de la fecha de C, el paso se saltea. No se usa `wa_policy_bypass`.
- **Variables:** {{1}} = nombre (campo del partner), {{2}} = código, {{3}} (solo B) = combo con precio.
- **Combo de B:** sale de los combos reales de la caja (`cf_combos`): el combo configurado (por defecto **Combo Lavadero Completo**, $18.900) más el segundo combo configurado si no llega a $20.000 (por defecto **Combo Ropa**, $6.490). Total $25.390, que con el 15% queda en **$21.582**. Si un combo no tiene stock, se usa el siguiente que lo supere. Parámetros `cristal_agent.event_coupon_combo_ids`.
- **Sin respuesta a A, B y C:** el contacto queda `finished` y no recibe nada más por este circuito.

### 3. Compra (para cortar la cadencia)
- El mismo cron (y un chequeo cuando se confirma la venta o se paga en el POS) marca `purchased` con el pedido, el importe sin IVA y el último paso enviado ("día 0", A, B o C).
- El lead pasa a **ganado**.
- **POS:** si el cajero no carga el cliente, la venta no se puede vincular. Igual cuenta en la medición global de usos del cupón (ver Medición). Queda como pendiente operativo para Guillermo: cargar el cliente por celular cuando presentan el cupón.

### 4. Después de la compra
- **D, día +3 (hábil, 10 a 19):** plantilla **259 `cristal_satisfaccion`** (utilidad, ya aprobada), con {{2}} = fecha de la compra. La respuesta ya se guarda sola (`agent_capture_survey`), y además se copia en las observaciones del partner.
- **E, día +30:** plantilla **258 `cristal_reposicion`** con {{2}} = el producto principal que llevó (la línea de mayor importe, sin la línea del descuento). No lleva descuento. Después el contacto queda `done` y pasa a la base general de consumidor final.
- La política de plantillas también aplica acá.

### 5. Bajas
- **Por la IA:** `mark_opt_out` (Claudio lo usa cuando el cliente dice "no me escribas", "baja", etc.) → `set_agent_opt_out`.
- **Por código, como respaldo:** si el entrante de un contacto del circuito es una baja clara ("baja", "no me escribas", "no me manden más"), se marca solo.
- **En los dos casos:** el contacto queda `opted_out`, sale de la lista "Evento <código>" (`mailing.subscription.opt_out`) y Claudio confirma la baja en una línea (la tool ya se lo indica).

### 6. Medición
En **Cristal Agent → Mayorista → 🎟️ Cupones de eventos**:
- **Ficha de cada evento:** contactos entrantes (leads con la etiqueta), contactos registrados por estado, usos del cupón (todos los pedidos web confirmados y los POS pagados con la recompensa, aunque la persona no esté registrada), facturación sin IVA de esas ventas, conversión (compras / contactos), compras por paso (día 0, A, B, C, sin vincular), costo de la mercadería regalada (`purchase_price` × cantidad del pedido de regalo) y facturación / costo.
- **Lista de contactos:** filtros y agrupación por evento, estado y paso.
- **Informe semanal de los lunes:** suma la sección "Cupones de eventos" con esos números, mientras haya un evento vigente o que haya vencido hace menos de 30 días.

### 7. Regla de conocimiento 132
La migración la reescribe (se busca por id 132 y, si no está, por el nombre con HISPANO15). El texto nuevo:
- Paso 1: responde con el cupón (igual que hoy).
- Paso 2: pide el nombre una vez. Ya no anota el origen a mano: lo hace el sistema.
- Paso 3: si quiere comprar, web o local; pedido por WhatsApp con envío → escala a Joaco; nunca arma un pedido con el 15%.
- Mantiene condiciones, mayorista y "no ofrecerlo a quien no lo pidió".
- Agrega: "**los recordatorios los manda el sistema (días 3, 10 y fin de enero); vos no agendes seguimientos ni actividades por este cupón.** Si contesta un recordatorio, conversá normal. Si pide la baja: mark_opt_out(kind=no_escribir) y confirmá en una línea".

### 8. Plantillas para Meta (las doy de alta en Odoo en **borrador**)
Cuenta Cristal Mayorista (8), modelo `res.partner`, idioma es_AR, categoría **MARKETING**, {{1}} = nombre del partner:
- `cupon_evento_recordatorio` (A): {{2}} código.
- `cupon_evento_combo` (B): {{2}} código y {{3}} combo.
- `cupon_evento_vence` (C): {{2}} código.

Los textos son los del documento. Las cadencias A, B y C quedan apuntando a esas plantillas y no envían hasta que Meta las apruebe. **Acción de Joaco:** abrir cada plantilla → "Enviar para aprobación" (o pedirme que las envíe), y controlar el estado en Meta.

## Pruebas en staging (pruebaAle), sin WhatsApp reales
- **Autotest (casos nuevos), en savepoint con el envío simulado:**
  - entrada con código, con mención sin código y mayorista;
  - registro sin duplicados;
  - fechas A, B y C, incluido el 24/01 domingo y una entrada de enero;
  - corte por compra web y POS, por baja y por tope de 3 mensajes;
  - postergación con ventana abierta y combo de B ≥ $20.000;
  - D y E;
  - medición.
- En staging, `enable_send_whatsapp` y las plantillas siguen apagados. La corrida real del cron se prueba con un `ir.actions.server` que termina en `UserError` (se revierte todo).

## Deploy
Rama `feat/cupon-evento` desde origin/main → cherry-pick sobre origin/pruebaAle → build verde + autotest → cherry-pick sobre origin/main → build verde → verificar en prod:
- versión 1.82.0;
- 2 eventos y 5 cadencias;
- KB 132 nueva;
- plantillas en borrador;
- cron activo.

## Decisiones con valor por defecto (Joaco puede cambiarlas)
1. **Equipo del lead:** Website (no hay equipo de consumidor final). Vendedor: OdooBot.
2. **D y E:** se reusan las plantillas 259 y 258, ya aprobadas, para no esperar a Meta. La 258 dice "próxima vuelta de reparto". Si no le gusta, se crea `cupon_evento_recompra`.
3. **Combo de B:** Lavadero Completo + Ropa, a $21.582 con el 15%.
4. **C:** lunes 25/01 (el 24/01 es domingo).
5. **Ventana abierta:** el paso se posterga, no se manda texto libre en medio de una charla.
6. **Cliente que ya compró antes** (no es primera compra): igual entra en la cadencia si es consumidor final. El cupón técnicamente no está limitado a la primera compra.
