# CHANGELOG — Cristal Agent

Todas las novedades del módulo se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) y el módulo
adhiere a [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [18.0.1.31.6] — 2026-08-03

### Added — Promos con precio cerrado (campañas / Meta Ads), NO acumulables con el 20%

Joaco lanzó un AD de "Jabón Ariel y Skip a $600 el litro". El bot no debía sumarle
el 20% de primera compra encima (el descuento no es acumulable).

- `create_sale_order`: las líneas aceptan **`price_unit`** (precio por unidad FIJO).
  Cuando viene, esa línea usa ese precio y **NO se le aplica `discount_percent`** (ni
  el 20%). El precio fijo se fuerza al final para que Odoo no lo recompute desde el
  pricelist. Las líneas sin `price_unit` siguen igual (20% / lista normal).
- Prompt v5: regla de **promos con precio cerrado** — cotizar con `price_unit` = el
  precio de la promo y sin `discount_percent`; NUNCA acumular el 20% encima.
- Oferta cargada (`cristal.agent.offer` #8): "Ariel + Skip a $600/L", con la nota de
  no-acumulable, prioridad baja (no interfiere con el broadcast).

Migración 1.31.6: recarga el prompt v5.

---

## [18.0.1.31.5] — 2026-07-28

### Changed — Búsqueda de productos INTERPRETATIVA (no literal)

El cliente casi nunca usa el nombre exacto del sistema. `search_products` hacía
match de TODAS las palabras (AND), así que *"perfume textil"* no encontraba
*"Perfume p/ropa"* (falta "textil") → el bot escalaba o decía que no había.

- `search_products`: si el match exacto falla, **relaja la búsqueda** con un mapa
  de sinónimos del rubro (textil↔ropa, lavavajilla→detergente, hipoclorito→lavandina,
  aromatizante→perfume, etc.) + búsqueda por la **palabra clave** sola, y devuelve
  candidatos marcados como `approximate` para que el bot elija el que corresponde.
- `create_sale_order` (`_resolver_producto`): mismo fallback por palabra clave al
  resolver productos para cotizar.
- Prompt v5: regla de interpretar el pedido (ej: "perfume textil" = "Perfume p/ropa",
  "lavavajilla" = "Detergente") y NO escalar ni decir "no tenemos" por diferencias
  de wording.

Migración 1.31.5: recarga el prompt v5.

---

## [18.0.1.31.4] — 2026-07-27

### Fixed — Al etiquetar Mayorista, setear la Lista Mayorista en la ficha (raíz)

Complemento del fix de cotizaciones: `update_partner`, cuando agrega la etiqueta
**Mayorista**, ahora también fija `property_product_pricelist` = 'Lista Mayorista'
(salvo que se pase otra pricelist explícita). Así los partners consumidor final
re-etiquetados mayorista dejan de conservar L.C 1 en su ficha, y cualquier flujo
(no solo el bot) cotiza con la lista correcta. Corrige la raíz progresivamente a
medida que el bot toca cada cliente. (Solo código; no requiere migración.)

---

## [18.0.1.31.3] — 2026-07-27

### Fixed — CRÍTICO: cotizaciones mayoristas salían con L.C 1 (precio consumidor final)

`create_sale_order` pedía la 'Lista Mayorista', pero Odoo **pisaba el pricelist del
pedido con el del partner** (`pricelist_id` se recomputa desde `partner_id`). Los
partners que eran consumidor final y se re-etiquetaron Mayorista conservaban su
`property_product_pricelist` = **L.C 1**, así que la cotización salía con precios de
consumidor final y se la pasaba al cliente (caso real: Sandra, S05330).

- Ahora la tool **fuerza SIEMPRE la Lista Mayorista** después de crear/reusar el
  borrador, **recomputa el precio de cada línea** desde esa lista y **reaplica el
  descuento** (cambiar el pricelist lo resetea).
- Resolución de pricelist **estricta**: si no existe la 'Lista Mayorista', NO cae a
  la del partner — devuelve error y escala. Nunca más L.C 1 en una cotización mayorista.

(Solo código; no requiere migración.)

---

## [18.0.1.31.2] — 2026-07-22

### Added — Lista de precios de UN solo nivel (ej: Oro para cliente preferencial)

`generate_pricelist_pdf` acepta un parámetro nuevo **`only_level`** (`bronce` /
`plata` / `oro`). Cuando se pasa, el PDF sale con **una sola columna de precio**
de ese nivel (con el descuento ya aplicado: plata −5%, oro −10%), el box de
niveles se reemplaza por un badge del nivel elegido, y el footer/nombre de archivo
lo reflejan. Ideal para mandarle a un cliente preferencial su precio final sin
mostrarle los otros niveles. Sin el parámetro, sigue saliendo la lista de 3
columnas de siempre. (Solo código; no requiere migración.)

---

## [18.0.1.31.1] — 2026-07-22

### Changed — Target mayorista afinado (comercios que revenden) + etiquetado temprano

Joaco marcó que Claudio derivaba mal: muchos dicen *"es para mi despensa"* (revenden
en su comercio) y el bot lo interpretaba como uso propio → derivaba a Compras.

- **Comercio propio = REVENDE = MAYORISTA.** Prompt v5: si el cliente tiene o arma un
  local donde le vende al público (despensa, kiosco, almacén, minimercado, dietética,
  verdulería, forrajería, ferretería, bazar, polirrubro, distribuidora, etc.) → es
  mayorista, NO uso propio. Derivar a Compras SOLO si es indudablemente institución de
  otro rubro para consumo propio (fábrica, escuela, hospital, oficina, etc.).
- **Ante la duda → ES MAYORISTA:** no derivar, no frenar; etiquetar, **mandar la lista**
  y seguir. Si se confirma, se pregunta sin frenar la venta.
- **Etiquetar al primer indicio:** al mínimo indicio de mayorista, `update_partner(
  category_to_add='Mayorista')` de una, sin esperar a cerrar la calificación.

Migración 1.31.1: recarga el prompt v5.

---

## [18.0.1.31.0] — 2026-07-22

### Changed — Iteración comercial: tono, canal con Joaco, autonomía, fuera de zona

Sobre datos reales de producción (534 runs / 1040 mensajes salientes en la
semana). Los problemas eran de formas y de negocio, no técnicos.

- **Tono garantizado (costo $0).** El prompt prohíbe las muletillas de festejo
  ("Perfecto", "Excelente", "Genial", etc.), pero Haiku igual las metía en
  **~13,5% de los mensajes** (1 de cada 7). Nuevo sanitizador determinístico
  `helpers.sanitize_tone()` que las saca del texto SALIENTE al cliente antes de
  enviarlo (`send_whatsapp`), sin costo de tokens. Conservador: solo actúa sobre
  muletillas de apertura, no sobre adjetivos legítimos. El canal interno no se toca.
- **Se elimina el chat con Joaco por WhatsApp.** A pedido de Joaco. `escalate_to_joaco`
  ahora escala **SOLO al canal interno de Odoo** (se quitó `_notify_owner_whatsapp`
  y el envío de la plantilla a su WhatsApp). Se agrega **throttle anti-repetición**
  al canal interno (no repite una escalación parecida en 6 h). `notify_owner_via_whatsapp`
  pasa a `False`.
- **Ultraautonomía: cero actividades para Joaco.** `cron_pending_activities` ya no
  crea una actividad manual para Joaco cuando un cliente se "traba": cierra la
  actividad y deja el log. Si de verdad necesita a Joaco, el bot escala por el
  canal interno.
- **Fuera de zona: SÍ se vende (retiro por comisionista).** Prompt v5: los clientes
  fuera de Río Cuarto/Las Higueras ya no se rebotan — se cotiza y vende normal con
  retiro por comisionista/encomienda en la planta de RC, y se los clasifica por
  ciudad/zona para la futura ruta de reparto. (Antes el prompt decía "no cotices",
  pero el bot ya vendía así igual — se oficializa y se pule.)
- **Calificación menos fría (dar valor primero).** Prompt v5: si el cliente abre
  pidiendo precio/lista/producto, el bot da eso PRIMERO (con el 20% OFF) y mete la
  pregunta en el mismo mensaje. Ya no condiciona la lista a que dé el email antes;
  el email se pide cuando hay interés. Menos interrogatorio, más venta.
- **Datos de transferencia en la KB.** Nueva entrada de conocimiento con los datos
  bancarios reales (Brubank / alias / CBU) para que el bot NUNCA invente un CBU
  (caso Juliana, a quien le pasó un CBU inexistente). El prompt apunta a usarlos textual.

Migración 1.31.0: recarga el prompt v5 y apaga `notify_owner_via_whatsapp`.

---

## [18.0.1.30.0] — 2026-07-06

### Fixed — El broadcast semanal mandaba el NOMBRE en vez de la oferta

El template `oferta_semanal_general` tiene {{1}} = nombre (campo automático) y
{{2}} = un solo texto libre. El broadcast pasaba DOS variables `[nombre, oferta]`,
así que el nombre caía en {{2}} y la oferta se perdía → salía *"Oferta de la
semana: <nombre del cliente>"* sin la promo. Ahora pasa **una** variable (la
oferta). Sin esto, disparar el cron mandaba mensajes vacíos de contenido.

### Added — CTA "YO" → avanza con el Combo Emprendedor

Para el broadcast del combo (responder "YO"): el bot ahora reconoce un "YO" como
intención de compra del Combo Emprendedor y avanza directo — cotiza el combo con
20% OFF, agrega las 3 muestras, detalla la lista literal y manda el PDF.

Migración 1.30.0: recarga el prompt.

---

## [18.0.1.29.0] — 2026-07-03

### Fixed — El bot no detallaba la cotización/combo (decía solo "sale $X")

El bot ofrecía el Combo Emprendedor o cotizaba diciendo solo el total ("te armé
el combo, sale $62.000 y van 3 muestras") sin listar los productos ni adjuntar el
PDF. Prompt reforzado: **prohibido decir solo "sale $X"** — el mensaje TIENE que
listar productos + cantidades (campo `lines`), nombrar las muestras gratis, y
adjuntar el PDF. Ejemplo de formato correcto incluido en el prompt.

Migración 1.29.0: recarga el prompt.

---

## [18.0.1.28.0] — 2026-07-02

### Added — Promo "3 muestras gratis" por compras +$60.000

Nueva promo (Meta Ads): compra > $60.000 → 3 muestras gratis (botellitas ~500ml),
acumulable con el 20% OFF.
- Nueva tool **`add_free_samples`**: identifica las muestras en stock (productos
  con "Muestra" en el nombre), las relaciona con su granel, y elige 3 de productos
  que el cliente **NO** compra (si ya lleva todo, 3 al azar). Las agrega GRATIS a
  la cotización y devuelve el **precio por litro** de cada granel para comunicarlo.
- Umbral $60.000 como **upsell**: si el total está por debajo, el bot ofrece las
  muestras como gancho para llegar. Solo se envían si llega a $60.000.
- `create_sale_order` devuelve `samples_hint` para guiar al bot.
- Seguimiento automático a **+2 días** (cómo va la venta + qué le parecieron las
  muestras) vía actividad del bot.

Migración 1.28.0: recarga el prompt.

---

## [18.0.1.27.0] — 2026-07-02

### Fixed — Combo Emprendedor: base 500cc → 1 lt

La línea del Combo Emprendedor que usaba la variante "Base Limpiador Desodorante
(1+80) Arpege, **500cc**" pasa a la de **1 litro** (decisión de Joaco). Migración
1.27.0 hace el swap (el modelo del combo no está expuesto al conector MCP).

---

## [18.0.1.26.0] — 2026-07-02

### Fixed — A Joaco no le llegaban los avisos (spam de escalaciones)

El bot escalaba el MISMO pedido a Joaco muchas veces seguidas; Meta acepta la
plantilla repetida ("sent") pero deja de entregarla → Joaco no recibía nada.
`escalate_to_joaco` ahora **throttlea**: si ya se avisó algo parecido en las
últimas 6 h, no lo repite por WhatsApp (el canal interno queda de log).

### Added — Checklist antes de confirmar un pedido

Antes de avisar "PEDIDO LISTO", el bot ahora: (1) confirma la **dirección de
entrega** exacta con el cliente; (2) pregunta si tiene los **bidones de 20 L**
para el recambio — si NO los tiene, informa **+$3.500 por cada bidón** y lo suma.

### Changed — Siempre adjuntar el PDF de la cotización

Reforzado en el prompt: nunca cotizar sin mandar el PDF adjunto (caso Abigail
Juárez, que no recibía el archivo).

Migración 1.26.0: recarga el prompt.

---

## [18.0.1.25.0] — 2026-07-02

### Fixed — Las notificaciones al operador quedaban en "sent" (no llegaban)

El partner operador había quedado resuelto con el número SIN el 9
(`+543585481191`). Meta acepta esos envíos ("sent") pero NO los entrega. El
WhatsApp real de Joaco es `+5493585481191` (con 9, partner "Joaco Ramello").
Migración 1.25.0: re-resuelve el operador prefiriendo el número CON el 9, así los
avisos se entregan de verdad. (En producción ya se corrigió en caliente.)

---

## [18.0.1.24.0] — 2026-07-02

### Fixed — Notificaciones al operador llegaban VACÍAS

La plantilla `hola_mayorista_crm` tiene `{{1}}` = nombre (campo automático) y
`{{2}}` = UN solo texto libre. `escalate_to_joaco` pasaba DOS variables, así que
el nombre caía en `{{2}}` y el mensaje real se perdía → a Joaco le llegaban avisos
vacíos ("Hola Carlos Ramello. Como estas? Carlos -"). Ahora pasa **una** variable
(el mensaje), igual que la cadencia.

### Fixed — El bot no podía sacar un producto de la cotización

No existía forma de quitar una línea de un presupuesto (solo agregar/mergear), así
que ante "sacame el desengrasante" el bot quedaba trabado. Nueva tool
**`remove_quote_product`**: quita el producto del draft del cliente, recalcula el
total y avisa si queda por debajo del mínimo.

### Fixed — El número operador ya no recibe cadencias/ofertas de cliente

El partner operador (WhatsApp de Joaco) se excluye de `cron_cadence_quoted` y del
broadcast de ofertas: aunque tenga una opp/cotización histórica, nunca se le manda
comunicación de cliente.

Migración 1.24.0: recarga el prompt (nueva tool).

---

## [18.0.1.23.0] — 2026-07-02

### Added — Nombre en los chats de WhatsApp (no el número)

Los chats de WhatsApp mostraban el número (ej: `5493585734625`). Ahora muestran
el **nombre del contacto** (perfil de WhatsApp, ya guardado en `whatsapp_partner_id`):
- **En vivo:** cada mensaje entrante sincroniza el nombre del canal con el nombre
  real del contacto (`_sync_whatsapp_channel_name`, idempotente).
- **Backfill:** migración 1.23.0 renombra todos los chats existentes (~1600).

Si el contacto no tiene nombre de perfil (solo número), el chat queda con el número.

---

## [18.0.1.22.0] — 2026-07-02

### Fixed — Calificación: no rebotar mayoristas reales

Claudio derivaba a Compras a mayoristas claros (ej: "micro emprendimiento de
limpieza"). Prompt reforzado: **micro-emprendimiento/emprendedor de limpieza =
MAYORISTA** (atenderlo, no derivar); derivar a Compras SOLO si es empresa/institución
para consumo propio de otro rubro; **ante la duda, PREGUNTAR — nunca derivar por
las dudas** (rebotar un mayorista real = error grave).

### Added — Operador por WhatsApp (reemplaza el chat interno)

El canal interno de Odoo se reemplaza por el **WhatsApp de Joaco (3585481191)**:
- **Saliente:** las escalaciones/urgencias/confirmaciones le llegan a Joaco por
  WhatsApp con la plantilla `hola_mayorista_crm` (el canal interno queda como log
  de respaldo).
- **Entrante:** los mensajes DESDE el número de Joaco se tratan como **órdenes del
  operador** (el bot obedece, ejecuta sobre los clientes y le responde por su
  WhatsApp) — **NUNCA como cliente** (no le vende ni lo califica).
- Config: `owner_whatsapp_number`, `owner_whatsapp_partner_id`,
  `notify_owner_via_whatsapp`. Nuevo `dispatch_agent_for_owner_whatsapp`.

Migración 1.22.0: recarga el prompt + resuelve/crea el partner operador.

---

## [18.0.1.21.0] — 2026-06-26

### Fixed / Changed — Claudio máquina de vender: cotización, mínimos, stock, autonomía

- **Cotización ÚNICA por cliente:** `create_sale_order` reusa el borrador abierto y
  mergea líneas — nunca más varios presupuestos para el mismo cliente.
- **Mínimo a granel 20L por producto, SIN excepción:** la tool rechaza líneas de
  granel con menos de 20L.
- **Mínimo de compra $50.000 con piso duro $39.990:** no se cotiza/envía por menos
  de $39.990; entre 39.990 y 50.000 avisa `upsell` para empujar a 50k.
- **Stock:** los productos de distribución/secos sin stock se marcan (`sin_stock`)
  para ofrecer alternativa / escalar; los granel de fabricación siempre disponibles
  (usa `is_storable`, compatible Odoo 18).
- **Cadencia de cotización:** seguimientos días 1 y 3; a los **+7 días sin
  confirmar la cotización se cancela sola** (`action_cancel`) y se manda un mensaje
  de reenganche ("se canceló por el tiempo, ¿la reactivamos para no perder el 20%?").
- **Actividades siempre al bot, NUNCA a Joaco** (`schedule_activity`).
- **Prompt v4 reforzado:** cotización única, precisión de producto (líquido de
  lampazo ≠ lampazo), stock → alternativa → escalar, mínimos + upsell, y
  **autonomía total** (escalar solo problemas graves tipo "Flor Gramajo").

Migración 1.21.0: recarga el prompt v4.

---

## [18.0.1.20.0] — 2026-06-26

### Changed — Usuarios permitidos por plantilla de WhatsApp (según cuenta)

Se setea `allowed_user_ids` en las plantillas según la cuenta:
- **Crilimp (8)** → Joaquín (18)
- **Ventas (9)** → Joaquín (18) + Alejandra (725)
- **Compras (5)** → Guillermo (15) + Sergio (2) + Joaquín (18)
- Info (3): sin cambios.

Migración 1.20.0 (bulk por cuenta). Las plantillas nuevas se asignan aparte.

---

## [18.0.1.19.0] — 2026-06-26

### Changed — Ocultar apps "avanzadas" del menú (solo Sergio y Joaquín)

Para despejar el menú superior del personal (Alejandra, etc.), se ocultan 7 apps
dejándolas visibles solo para Sergio (2) y Joaquín (18):
**Aplicaciones, Eventos, Empleados, Sitio web, Planeación, Suscripciones e
Información (Knowledge).**

- Nuevo grupo `group_apps_internas` (solo Sergio/Joaquín).
- Migración 1.19.0: gatea el menú raíz de esas apps a ese grupo, buscándolos por
  nombre (es + en) para no depender de xmlids internos. Lo que no matchea se ignora
  (no rompe el deploy). Reversible.
- No se tocan permisos funcionales de nadie; es solo visibilidad de menú.

---

## [18.0.1.18.0] — 2026-06-26

### Changed — Acceso restringido: solo Sergio y Joaquín ven el módulo

El menú raíz de Cristal Agent no tenía grupo → lo veía todo el personal (Alejandra
incluida). Ahora:

- Nuevo grupo `group_cristal_agent_access` (Cristal Agent · Acceso interno) con
  **solo Sergio (id 2) y Joaquín (id 18)**.
- El menú raíz `menu_cristal_agent_root` queda restringido a ese grupo → el resto
  del personal ya no ve ni entra al módulo.
- Se gestiona desde Ajustes → Usuarios (el grupo es administrable; `noupdate`).
- No se tocó el acceso a los modelos (el bot y el conector entran por API/sudo,
  restringirlos los rompería); la restricción es de menú/visibilidad, que es lo
  que saca a Alejandra del módulo.

(Mismo criterio aplicado al módulo "Reporte Plan Control" — `quimica_cristal_reporte_mensual` v18.0.1.2.0.)

---

## [18.0.1.17.0] — 2026-06-26

### Fixed — El bot no encontraba el template de seguimiento (escalaba en vez de mandar)

`send_whatsapp_template` buscaba el template solo por el campo `name` ("Hola
Mayorista crm"), pero el bot pasaba el nombre técnico `template_name`
("hola_mayorista_crm") → "template no existe" → el bot escalaba a Joaco en vez de
mandar el seguimiento con ventana cerrada.

- **FIX:** ahora busca por `name` **o** `template_name` (case-insensitive). El bot
  puede pasar cualquiera de los dos.

### Added — Catch-up del backlog de cotizaciones

- `cron_cadence_quoted` ahora hace **catch-up**: las cotizaciones que nunca tuvieron
  seguimiento (`last_cadence_step_executed < 0`) reciben **un toque** aunque estén
  fuera de los días [1,3,7]. Las nuevas siguen el ritmo normal 1/3/7.
- **Migración 1.17.0:** resetea el contador de las cotizaciones en cola
  (`phase_2_quoted`) para que en la próxima corrida del cron se disparen **todas**
  los pendientes — ahora que el template funciona.

---

## [18.0.1.16.0] — 2026-06-24

### Added — Seguimiento autónomo de cotizaciones (días 1/3/7)

Faltaba la única cadencia que quedaba manual (el ida y vuelta del canal interno):
el seguimiento de **cotizaciones enviadas**. Había crons autónomos para post-muestra
(Fase 2) y post-compra (Fase 3), pero ninguno para `phase_2_quoted`.

- **Nuevo cron `cron_cadence_quoted`** (cada 6hs, activo): para cada oportunidad en
  "Cotización enviada" sin cerrar, a los días **1, 3 y 7** desde la cotización
  (referencia = última `sale.order` colgada de la opp), dispara al bot para que
  mande un seguimiento **autónomo** (recuerda total + 20% off + formas de pago).
  Máx 3 toques y para. Si el cliente responde/compra, la fase cambia y se corta.
- **Sin canal interno**: el bot manda solo — `send_whatsapp` si la ventana 24hs
  está abierta, o el template **`hola_mayorista_crm` (236)** rellenando el texto
  libre `{{2}}` si está cerrada. No escala a Joaco.
- `create_sale_order` ahora marca `agent_managed=True` en la opp y resetea el
  contador de cadencia para que el seguimiento arranque limpio desde la cotización.
- Nuevo flag `enable_quoted_cadences` (default ON) en Configuración → Habilidades.

**Dependencia:** el seguimiento con ventana cerrada necesita que Meta **apruebe el
template 236** (`hola_mayorista_crm`); hasta entonces, los seguimientos con ventana
abierta funcionan y los de ventana cerrada quedan a la espera.

---

## [18.0.1.15.0] — 2026-06-24

### Changed — El bot opera como OdooBot (se da de baja el usuario Claudio)

Para no pagar una licencia de usuario dedicada, el bot deja de actuar como el
usuario **Claudio** (res.users 721 / res.partner 80799) y pasa a operar como
**OdooBot** (res.users 1 / res.partner 2), el usuario de sistema (sin costo).

- **Config** (en vivo): `bot_user_id` → OdooBot (1), `bot_partner_id` → OdooBot (2).
- **Código**: todos los fallbacks hardcodeados a 721/80799 ahora apuntan a 1/2
  (`create_lead`, `confirm_sample_sent`, `send_whatsapp`, `escalate_to_joaco`,
  `read_message_history`, `prompt_builder`, `__init__` post-init). `INTERNAL_PARTNER_IDS`
  suma el partner de OdooBot (2).
- **Migración 1.15.0**: reasigna a OdooBot todo lo que estaba como Claudio —
  oportunidades (crm.lead, incl. archivadas), actividades (mail.activity) y órdenes
  de venta (sale.order) — para poder dar de baja el usuario Claudio sin dejar
  registros colgados.

Tras el deploy, Joaco puede archivar/eliminar el usuario Claudio (721) y liberar
la licencia.

---

## [18.0.1.14.0] — 2026-06-23

### Fixed — CRÍTICO: la transcripción de audio bloqueaba el webhook

En v1.13.0 la transcripción corría **sincrónicamente dentro del `create()` del
mensaje**, o sea **dentro del request del webhook de Meta**. Una nota de voz
disparaba una llamada HTTP a OpenAI (hasta 60s) que **bloqueaba la respuesta a
Meta**; con timeouts repetidos, Meta corta la entrega y dejan de entrar mensajes
(de cualquier tipo). Se neutralizó en caliente apagando `enable_audio_transcription`
por config; este release lo arregla de raíz.

- La transcripción ahora es **100% asíncrona**: el webhook solo **marca** el audio
  (`memory.enqueue_pending_audio`) y responde al instante. La llamada a OpenAI
  corre en el **cron** (`cron_process_debounced`), fuera del camino del webhook.
- Las notas de voz **siempre** van por la cola async (sin importar el debounce),
  para que OpenAI nunca pueda volver a colgar la recepción.
- Nuevo campo `cristal.agent.memory.pending_audio_att_ids` (Json) que encola los
  ids de attachment de audio a transcribir.
- El cron junta la transcripción con el texto pendiente (`[nota de voz] …`) y
  dispara un único run. Si no se puede transcribir y no hay texto, avisa a Joaco.
- Timeout de la llamada a OpenAI bajado 60s → 30s (defensa extra).

### Nota operativa
Tras deployar, re-activar `enable_audio_transcription` en Configuración (quedó
apagado por la mitigación en caliente). Recordar que el rebuild del deploy puede
pausar el webhook de Meta → re-verificarlo.

---

## [18.0.1.13.0] — 2026-06-23

### Added — Lector de notas de voz (transcripción de audio)

La API de Claude no acepta audio (solo texto, imágenes y PDF). Hasta ahora las
notas de voz que mandaba un cliente se perdían en silencio (el inbound cortaba al
no encontrar texto). Ahora:

- **Nuevo `services/transcription.py`**: toma el `ir.attachment` de audio (.ogg/opus
  de WhatsApp) y lo transcribe con **OpenAI** (`gpt-4o-transcribe`) vía
  `requests`/multipart. Devuelve el texto o `None` si falla.
- **`whatsapp_message._maybe_trigger_agent`**: si llega un mensaje sin texto pero
  con audio adjunto, lo transcribe y lo procesa como si el cliente lo hubiera
  escrito (con prefijo `[nota de voz]`). El resto del flujo (debounce, Claude,
  cotización) sigue igual.
- **Si la transcripción está apagada o falla**: el bot avisa a Joaco por el canal
  interno para que escuche el audio a mano (ya no se pierde en silencio).
- **Config** (`cristal.agent.config`): `enable_audio_transcription` (default OFF),
  `openai_api_key` (guardada en `ir.config_parameter`), `transcription_model`
  (default `gpt-4o-transcribe`), `transcription_language` (default `es`). UI en
  Configuración → 🔑 API de Anthropic.
- **Prompt v4**: explica el prefijo `[nota de voz]` y que las notas de voz que no
  se pueden transcribir las escala el sistema solo.

### Migration
- `migrations/18.0.1.13.0/post-migration.py`: recarga el prompt v4 y fija defaults
  de transcripción (queda **apagada** hasta que se cargue la OpenAI API Key).

---

## [18.0.1.12.0] — 2026-06-23

### Fixed — La cotización SIEMPRE cuelga de una oportunidad

`create_sale_order` quedaba "en el aire": creaba la sale.order pero no la ligaba a
ninguna oportunidad ni movía el pipeline. Ahora:
- Busca la oportunidad abierta del cliente (o **la crea** si no existe) y setea
  `order.opportunity_id`, así la cotización aparece en el CRM colgada del lead.
- Avanza la fase a **Propuesta enviada** (`phase_2_quoted`) y deja un mensaje en
  el chatter de la oportunidad.

### Added — Combo Emprendedor (combo fijo configurable)

- Nuevo modelo `cristal.agent.combo.line` + campos en `cristal.agent.config`
  (`combo_emprendedor_active/name/pitch/line_ids`): cargás un combo fijo
  (productos + cantidades) desde Configuración → Habilidades.
- `prompt_builder` inyecta el combo activo al contexto del bot ("🎁 COMBO
  EMPRENDEDOR"). El bot lo ofrece a los clientes que **arrancan** y lo cotiza con
  el **20% off** de primera compra (borrador, Joaco confirma).
- Prompt v4 actualizado con el puntero al combo.

### Migration
- `migrations/18.0.1.12.0/post-migration.py`: recarga el prompt v4 y fija el
  nombre por defecto del combo.

---

## [18.0.1.11.4] — 2026-06-15

### Changed — Fase 1: vendedor que cotiza, sin muestras (prompt v4)

Cambio estratégico del flujo comercial. Se elimina la entrega de muestras y el
bot pasa a comportarse como vendedor que asesora, dice precios y cotiza.

- **Sin muestras:** se quita todo el flujo de muestras (kit fijo, detección de
  confirmación, cadencia post-muestra). Si piden muestra, el bot reorienta al
  gancho nuevo. Flag `enable_confirm_sample=False`.
- **Gancho = 20% OFF primera compra** (reemplaza la muestra como gancho).
- **El bot dice precios y cotiza:** prompt `claudio_v4.md`. Puede consultar
  precios (`search_products` sobre Lista Mayorista) y armar cotizaciones
  (`create_sale_order`) en **BORRADOR**; la venta la **confirma Joaco**.
- **`create_sale_order`** acepta `discount_percent` (20 para el gancho de primera
  compra, aplicado a todas las líneas). **`search_products`** ahora calcula el
  precio sobre la Lista Mayorista (no la del partner) para cotizar bien.
- **KB:** se da vuelta la regla "PROHIBIDO pasar precios" (ahora el bot cotiza en
  borrador y Joaco confirma) y se desactivan las entradas de KB de muestras.
- Flags `enable_create_sale_orders` y `enable_generate_quote_pdf` en True.

Pendiente Fase 2: "Combo Emprendedor" (combo fijo configurable) para los que
arrancan.

### Migration
- `migrations/18.0.1.11.4/post-migration.py`: recarga prompt v4, ajusta flags,
  reescribe la KB de precios y desactiva la KB de muestras.

---

## [18.0.1.11.3] — 2026-06-15

### Changed — Lista de Precios: 3 columnas de nivel por producto

Sobre el rediseño 1.11.2, se reponen las **3 columnas de precio por nivel**
(BRONCE / PLATA −5% / ORO −10%) en cada fila, manteniendo todo lo demás
(líquidos primero, líneas visibles, columna UNIDAD, "a consultar" si no hay
precio). Encabezados con el % de descuento para que se entienda de una.

---

## [18.0.1.11.2] — 2026-06-15

### Changed — Rediseño de la Lista de Precios Mayorista (PDF)

`generate_pricelist_pdf` rediseñado, más claro y mejor segmentado:

- **Líquidos primero:** dos secciones con banner — *"LÍQUIDOS A GRANEL ·
  Fabricación propia"* (Fabricación + Fraccionado) arriba, *"DISTRIBUCIÓN · Línea
  seca y reventa"* abajo.
- **Nombres de línea visibles:** sub-header por línea (Línea Lavandería,
  Detergente, Desengrasante, Lavandina, etc.), ordenadas comercialmente.
- **Precios más claros:** columna UNIDAD ("x litro" / "x unidad") + un único
  precio mayorista (base) por fila; las tarifas por nivel se explican en el box y
  el footer. Productos sin precio cargado muestran "a consultar" en vez de $0.
- Estética: banners, headers de línea, filas alternadas, tipografía legible.

Sin cambios de esquema ni migración (solo el generador del PDF).

---

## [18.0.1.11.1] — 2026-06-15

### Added — Broadcast de campaña a seleccionados (server-side)

Odoo estándar NO tiene envío masivo de WhatsApp desde la lista (sí email/SMS), y
el bot no puede mandar 67+ en una corrida por el límite de iteraciones. Para las
ofertas semanales a un segmento puntual (ej: mayoristas de Río Cuarto sin compras):

- **Acción de servidor "Enviar campaña WhatsApp"** (`data/campaign_broadcast.xml`)
  sobre `crm.lead`, visible en el menú **Acciones** de la lista/ficha. Recorre los
  leads SELECCIONADOS y manda el template configurado, **server-side, sin el límite
  de iteraciones del bot**. Dedup por partner, saltea takeovers, reusa el envío
  nativo (`whatsapp.composer` vía `SendWhatsappTemplate`), que resuelve solo el
  header de imagen y las variables.
- Campo `campaign_template_id` en `cristal.agent.config`: el template que envía la
  acción; se cambia cada semana por la oferta de turno.
- Flujo semanal: CRM → filtrar por etiqueta de campaña → seleccionar → Acciones →
  Enviar campaña WhatsApp.

### Migration
- `migrations/18.0.1.11.1/post-migration.py`: setea `campaign_template_id` al
  template `combo_mayorista_hoy` (si existe y está aprobado).

---

## [18.0.1.11.0] — 2026-06-12

Revisión integral de costo + "formas" + canal interno + segmentación geográfica.
Diagnóstico sobre datos reales de producción (839 runs en 7 días, ~120/día; 0
errores técnicos — los problemas eran de calidad/costo, no crashes).

### Changed — Costo (la palanca grande)

- **System prompt partido en bloque ESTABLE (cacheado) + bloque DINÁMICO (sin
  cachear).** Causa raíz del costo: el contexto por-cliente (ficha +
  observaciones) vivía DENTRO del bloque cacheado, y como el bot actualiza
  observaciones casi en cada charla (R8), el prefijo cambiaba y el cache se
  reescribía en ~todos los runs (cache WRITE a 2x de la TTL 1h = lo más caro).
  Ahora `build_system_prompt` devuelve `(stable, dynamic)`: el estable (prompt +
  reglas + KB global + ofertas) es idéntico para todos los clientes → se escribe
  una vez por hora y lo reusan los ~120 runs/día; el dinámico (ficha del cliente)
  va después del breakpoint, como input barato. Recorte estimado ~70-80% del
  componente de system.
- **Debounce de ráfagas (10s, configurable).** Antes se disparaba un run completo
  por CADA mensaje entrante, sincrónico dentro de `whatsapp.message.create()`
  (caso real: 9 mensajes/9 runs en 5 min para una sola calificación). Ahora los
  mensajes de una ráfaga se encolan en la memoria y se procesan TODOS en un único
  run tras N segundos de silencio (`cron_process_debounced` + `_trigger` one-shot,
  con cron de 1 min de fallback). Menos runs, menos costo y respuesta más
  completa/menos "spam".
- **Cálculo de costo correcto por modelo.** `agent_run._compute_cost` cobraba TODO
  con precios de Sonnet aunque el tráfico corre en **Haiku 4.5** → inflaba el
  costo reportado ~3x. Ahora hay tabla de precios por modelo (haiku/sonnet/opus,
  con cache write a 1h = 2x) y un campo `model_used` que se graba en cada run.

### Changed — Formas (calidad de los mensajes al cliente)

- **Prompt mayorista reescrito a `claudio_v3_2.md`.** Las reglas de tono estaban
  enterradas en 488 líneas y Haiku no las respetaba (decía "Perfecto", "Genial",
  emojis en cadena, saludos de animador). v3.2: el tono va PRIMERO, con lista de
  palabras prohibidas y la regla "si vas a escribir una, borrala y reescribí";
  preguntas AGRUPADAS (nombre+email juntos, etc.) para cortar la fragmentación;
  consciente del debounce ("te llegan los mensajes juntos, respondé una vez").
- **Switch opcional de modelo fuerte para clientes** (`escalate_client_msgs_to_strong`,
  OFF por default). Si las formas con Haiku no alcanzan, prendelo y cargá un
  Sonnet en `anthropic_model_complex`: se usa SOLO para redactar mensajes a
  clientes, dejando lo interno y los cron en Haiku. Costo-primero por default.

### Changed — Canal interno con Joaco

- Respuestas endurecidas: **máximo 1 línea, texto plano, sin tablas markdown ni
  "✅ Resumen"**, y **no responde si no hay acción que tomar**. Antes contestaba
  con tablas markdown (se ven mal en WhatsApp/Discuss) y mensajes largos.

### Added — Segmentación geográfica

- Campo `agent_zone` en `res.partner` (Río Cuarto / Las Higueras / Fuera de zona /
  Otra / No relevada), indexado y con tracking. La ciudad va al campo nativo
  `city`. `update_partner` acepta `city` + `agent_zone` y auto-etiqueta "Fuera de
  zona". El prompt v3.2 obliga a capturar ciudad+zona en la calificación.
- Vista de partner con sección "Ubicación / zona" + filtros y group-by por zona y
  ciudad para segmentar la base mayorista (preparación para armar zonas de reparto).

### Migration

- `migrations/18.0.1.11.0/post-migration.py`: recarga el prompt v3.2, fija
  defaults (`debounce_seconds=10`, `escalate_client_msgs_to_strong=False`) y
  asegura la etiqueta "Fuera de zona".

---

## [18.0.1.10.5] — 2026-06-09

### Fixed

- **Cierre atómico institucional fallaba con AccessError (rollback total).** El
  agente entra como usuario público (id 715, sin permisos CRM). Los `.sudo()` de
  las tools alcanzaban, pero al pasar el lead a stage 14 (Calificado) un
  side-effect del framework tocaba `crm.lead` bajo el público y rebotaba contra
  una record rule, haciendo rollback de todo el cierre: el bot mandaba el mensaje
  pero el lead quedaba en "Contactado", sin empresa/contacto/actividad, y el
  takeover quedaba con `takeover_reason = "Cierre atómico falló…"`. Ahora los
  dispatchers (`_for_message`, `_for_cron`, `_for_activity`,
  `_for_internal_message`) rebindean el env a `SUPERUSER_ID` al inicio, así todo
  el árbol (ClaudeClient → tools → cierre atómico) corre con permisos plenos.

- **Falso `WINDOW_CLOSED` al responder un inbound.** El chequeo de ventana 24hs
  de `send_whatsapp` rebotaba contra el mismo mensaje entrante recién recibido,
  bloqueando la respuesta (caso real: Silvia Bazán, partner 80526, run 1269).
  Ahora, si el run lo disparó un inbound (`trigger='whatsapp_message'`), se
  saltea el chequeo: la ventana está abierta por definición. Los envíos
  proactivos del cron siguen respetando el chequeo.

- **Mensaje de cierre se mandaba aunque la calificación fallara.** El prompt
  institucional disparaba el cierre y mandaba "¡Listo, {nombre}! Tomé nota de
  todo…" sin importar el resultado de `complete_institutional_qualification`.
  Endurecido en `claudio_institutional_v2.md`: el mensaje de cierre se manda
  SOLO si la tool devuelve `ok=true`; si devuelve `ok=false`/error, el bot manda
  una línea neutra, escala a Joaco con el error y pausa con `pause_bot(2h)`.

### Changed — Optimización de costos (API Anthropic)

Diagnóstico sobre 60 runs recientes en producción (Haiku 4.5): el **62.8% del
costo era cache WRITE** — se pagaba un write de ~17k tokens en *casi todos* los
runs, incluso en mensajes seguidos del mismo cliente con 1 minuto de diferencia.

- **Causa raíz: prefijo cacheado inestable.** El system prompt embebía el
  timestamp con precisión de minuto (`%H:%M`) dentro del bloque cacheado, así que
  el texto cambiaba cada minuto y el cache se invalidaba en cada mensaje. Se sacó
  el minuto del bloque cacheado (queda fecha + día, estable todo el día); la hora
  exacta ahora va en el `user_message` (que no se cachea). Esto convierte el grueso
  de los cache WRITE en lecturas baratas. **Este era el verdadero driver del costo
  — sin esto, el cache de 1h no servía de nada.**
- **Cache de 1h (beta).** Header `anthropic-beta: extended-cache-ttl-2025-04-11` y
  `cache_control` con `ttl="1h"` en el system, la última tool y el último mensaje
  del historial. El prefijo (estable) sobrevive 1h, así los mensajes del mismo
  cliente reusan el cache aunque lleguen con minutos/decenas de minutos de
  diferencia.
- **Prompt institucional achicado** ~24% (≈3.6k → ≈2.7k tokens): se sacó el bloque
  "RESUMEN DEL ORDEN OPERATIVO" (duplicaba STEP 0-4) y redundancias entre
  secciones, conservando STEP 0/1/2/3/4, las burbujas de copy y la tabla de rubros.
- **Trim de historial:** `read_message_history` baja su default de 15 → 10 mensajes
  y el cap por mensaje de 1000 → 600 chars; el prompt interno baja `limit=20 → 10`.
- **Modo híbrido opcional (TODO activable):** nuevo campo `anthropic_model_complex`
  en la config. Vacío por default (todo en Haiku). Si Haiku patina con el cierre,
  cargá ahí un Sonnet y se usa SOLO en tareas complejas (`joaco_command` / cron),
  dejando el grueso del tráfico WhatsApp en Haiku.

Ahorro estimado sobre el ya-Haiku: ~40-45% adicional (de ~$62 a ~$35/mes a este
volumen). Combinado con el switch previo a Haiku, el recorte total vs. el baseline
Sonnet supera el 70%.

### Migration

- `migrations/18.0.1.10.5/post-migration.py` recarga el prompt institucional
  achicado + cierre endurecido en la config activa.

---

## [18.0.1.10.4] — 2026-06-01

### Fixed — Lead/contacto mal etiquetado con el nombre del perfil de WhatsApp

Al crear el lead temprano, el `contact_name` y el partner quedaban con el nombre
que trae el perfil de WhatsApp del que escribe (en la prueba: "Química Cristal",
porque el teléfono de test tiene ese nombre de perfil). El nombre de la oportunidad
salía bien, pero el contacto del lead quedaba sucio.

- `create_lead` ahora acepta `contact_name` y `company_name` y los graba en el lead
  (`contact_name` / `partner_name`), en vez de dejar que Odoo los autocomplete desde
  el nombre del partner.
- Si el contacto es fresco (autocreado por WhatsApp: no es company, sin `parent_id`,
  sin email), `create_lead` le pone el nombre real capturado en la conversación.
- STEP 2 del prompt institucional ahora pasa `contact_name` y `company_name`.
- `migrations/18.0.1.10.4/post-migration.py` recarga el prompt.

Nota: el origen del "Química Cristal" era el nombre de perfil de WhatsApp del teléfono
de prueba (Odoo nombra el contacto con eso). En un cliente real sería su nombre/perfil.
El fix hace que, igual, el lead quede con los datos reales de la charla.

---

## [18.0.1.10.3] — 2026-06-01

### Fixed — Confirmación en medio del flujo clasificada como "ruido"

El STEP 0 clasificaba cada mensaje aislado por su texto. Una confirmación en plena
calificación ("asi es" tras "¿en Río Cuarto?") caía en ruido → el bot se quedaba en
silencio y cortaba el flujo.

- `prompt_builder` ahora inyecta el ESTADO DEL HILO en el mensaje: HILO ACTIVO (el
  bot ya intervino — hay `qualification_data` y/o mail.message con `author_id` =
  bot en el canal) vs MENSAJE FRÍO.
- STEP 0 reescrito: en HILO ACTIVO el mensaje es continuación/respuesta y NUNCA es
  ruido (las confirmaciones cortas son respuestas válidas → seguí el flujo). En
  MENSAJE FRÍO: lead claro → corre el flujo; no-lead (operativo/social/ruido) →
  escala a Joaco + `pause_bot(0)`.
- Se elimina el silencio a nivel prompt; el silencio queda solo para takeover activo
  (nivel código, post-calificación).
- `migrations/18.0.1.10.3/post-migration.py` recarga el prompt v2 corregido.

---

## [18.0.1.10.2] — 2026-06-01

### Added — Subida del reporte de muestra desde la config (UI)

El campo `institutional_report_attachment_id` (Many2one) no daba un upload cómodo.
Ahora hay un campo de subida de archivo en Config → Institucional:
- `institutional_report_pdf` (Binary) + `institutional_report_pdf_filename`.
- Al subir un PDF y guardar, el `write` crea un `ir.attachment` standalone y setea
  `institutional_report_attachment_id` (el que adjunta `send_whatsapp` en STEP 3).

Recordatorio: subir una muestra ANONIMIZADA, nunca el reporte real de un cliente.

---

## [18.0.1.10.1] — 2026-06-01

### Fixed — WINDOW_CLOSED falso por resolución de partner incorrecta en send_whatsapp

`send_whatsapp` resolvía el partner para el chequeo de ventana de 24hs adivinando
desde `channel_partner_ids` (primer miembro que no fuera bot ni owner). Si en el
canal había un operador interno (Guillermo, Adrian, etc. — que quedan como miembros
cuando responden manual desde Discuss), el chequeo miraba el historial de ESE
operador (sin inbound reciente → 999hs) y devolvía `WINDOW_CLOSED` aunque el cliente
acabara de escribir. El bot entonces escalaba a Joaco en vez de responder.

- Ahora el chequeo usa `run.partner_id` (el remitente real que disparó el run).
- El fallback por miembros del canal excluye TODOS los `INTERNAL_PARTNER_IDS`, no
  solo bot+owner.

Detectado en prueba post-deploy: mensaje desde 3585481199 (línea interna, canal
preexistente con Guillermo como miembro) → WINDOW_CLOSED → escalado. Sin cambios de
esquema; fix solo de código.

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
