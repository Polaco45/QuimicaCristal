# Cristal — Ruteo de Visitas (`cristal_ruteo`)

Planificador de rutas de visita para la fuerza de venta de calle, estilo **PJP
(Plan de Jornada Permanente)** de distribuidora FMCG. Se apoya en el motor de
valor que ya calcula `cristal_agent` (nivel, compras, churn, zona macro) y agrega
la capa geográfica + de ruteo.

## Roadmap (pieza por pieza)

### v2.0 — Operación y control (v18.0.2.0.0)

- **Modelo `cristal.ruta.visita`**: registro de trabajo/control de cada visita
  (estado, resultado, notas, posposiciones, origen auto/manual, vínculo a la
  oportunidad del CRM). Reemplaza a las actividades nativas como fuente de verdad.
- **Vista Kanban dinámica** ("Mi ruta de hoy"): tarjetas por estado, arrastrar y
  soltar, botones *Cómo llegar* / *Visité* / *Posponer*. La vendedora puede
  **agregar** visitas a mano (Nuevo), **posponer** (asistente) y **sacar** de la ruta.
- **Control de visitas** (para gerencia): lista + pivot de qué pasó con cada
  cliente por día/vendedor/estado/resultado, y **reporte diario por email**.
- **Geolocalización en masa**: acción *"Geolocalizar seleccionados"* en la lista
  de contactos y de oportunidades (seleccionar varios → ubicar todos).
- **Sin dirección**: los clientes sin calle/ciudad quedan con estado *"Sin
  dirección"* (filtro), no se pierden en silencio.
- **Geo más segura**: chequeo de caja geográfica — si el geocodificador devuelve
  un punto fuera de Río Cuarto (centroide genérico), se marca *"Revisar"* en
  vez de darlo por bueno.

### v1 — Piezas base

1. **Geolocalización automática** ✅ *(v18.0.1.0.0)*
2. **Micro-zonas de ruta** (`cristal.ruta.zona`) con día de la semana ✅ *(v18.0.1.1.0)*
3. **Frecuencia por valor + próxima visita** ✅ *(v18.0.1.2.0)*
4. **Score de prioridad + tipo de visita** ✅ *(v18.0.1.3.0)*
5. **Generador de ruta diaria** (cron → actividades numeradas) ✅ *(v18.0.1.3.0)*
6. **Vista "Mi ruta de hoy"** ✅ *(v18.0.1.3.0)*

## Pieza 1 — Geolocalización automática

**Qué hace:** la vendedora carga la **dirección de calle** del cliente y el
sistema lo ubica solo en el mapa (coordenadas `partner_latitude/longitude`),
listo para entrar al recorrido.

**Cómo funciona (desacoplado del guardado, robusto):**

- Al crear/editar la dirección se marca `ruteo_geo_pending = True`. Es barato y
  no bloquea el save ni rompe importaciones masivas.
- El cron *"Cristal Ruteo: Geolocalizar clientes pendientes"* corre cada ~10 min,
  toma los pendientes **de carteras de vendedores** (`user_id` seteado, no los
  miles de contactos sueltos) y los geolocaliza respetando el rate-limit del
  proveedor (Nominatim: ≤1 req/seg).
- Botón **"Geolocalizar ahora"** en la pestaña *Ruteo de visitas* de la ficha,
  para ubicar un cliente al instante.

Todo el geocodificado está envuelto en `try/except`: nunca rompe un guardado ni
el cron por un fallo del proveedor. El estado queda visible en `ruteo_geo_status`
(pendiente / ubicado / falló) con el detalle del error si lo hubo.

**Proveedor:** usa **georef** (apis.datos.gob.ar), el geocodificador oficial
argentino — gratis, sin API key y mucho más preciso que OpenStreetMap para
direcciones locales (OSM falla o erra en Río Cuarto). Si el cliente no tiene
ciudad cargada, se asume Río Cuarto (o Las Higueras según la zona) para no
geocodificar a ciegas. Si no matchea la altura exacta, ubica la calle y marca
"Revisar". El módulo usa los campos de `base_geolocalize` (lat/long).

## Pieza 2 — Micro-zonas por día (PJP)

**Qué hace:** parte la cartera del vendedor en zonas geográficas compactas y le
da a cada zona un día de la semana, para que la vendedora viaje concentrada
(estilo Plan de Jornada Permanente de distribuidora).

**Cómo se arma:** menú *Ruteo de Visitas → Armar zonas automáticamente*. Elegís
el vendedor y la cantidad de zonas (5 = Lun a Vie). El sistema agrupa los
clientes **ya geolocalizados** por cercanía (k-means puro, determinista, sin
librerías externas por el sandbox de Odoo.sh) y ordena las zonas de oeste a
este para asignar Lunes→Viernes. Todo editable a mano después.

**Modelo `cristal.ruta.zona`:** nombre, vendedor (`user_id`), día (`weekday`),
clientes (`partner_ids`), conteos y centroide (`center_latitude/longitude`).
En `res.partner` se agrega `ruteo_zona_id` y `ruteo_weekday` (día de visita,
derivado de la zona, filtrable).

## Pieza 3 — Frecuencia por valor + próxima visita

Le dice al sistema **a quién le toca** cada semana. En `res.partner`:

- `ruteo_frequency_days` (derivado del nivel): oro=7, plata=15, bronce=30,
  nuevos/prospectos=15 (captación). Se actualiza solo cuando cambia el nivel.
- `ruteo_last_visit`: fecha de la última visita presencial (la setea el cierre
  de la actividad de visita — Pieza 5 — vía `_ruteo_register_visit()`).
- `ruteo_next_visit_due`: última visita + frecuencia. Vacío = nunca visitado.
- `ruteo_is_due`: le toca (ya venció la próxima o nunca fue visitado).

Filtros nuevos en Contactos: **Le toca visita**, agrupar por **Día de visita**
y por **Zona de ruteo**.

## Piezas 4-6 — Prioridad, ruta diaria y "Mi ruta de hoy"

**Pieza 4 — Prioridad y tipo de visita.** En `res.partner` (computados):
`ruteo_visit_type` (primera visita / relevamiento / cierre / reposición /
reactivación) según la etapa de la mejor oportunidad abierta del cliente + si
ya es cliente + churn; `ruteo_priority_score` (base por tipo + urgencia si le
toca + churn + nivel) que define el orden; `ruteo_pin_color` para el mapa/kanban.

**Pieza 5 — Generador de ruta diaria.** Cron *"Cristal Ruteo: Generar ruta del
día"* (06:00 ARG): para cada zona cuyo día coincide con hoy, toma los clientes
que le tocan, los ordena por prioridad y luego por cercanía (vecino más cercano
desde el centroide de la zona), cap 9 visitas, y crea una actividad **"Visitar
Institución"** numerada en cada cliente. Es idempotente (regenera sin duplicar).
Al **cerrar** la actividad se registra `ruteo_last_visit` y se recalcula la
próxima visita. Botón/menú **Generar ruta de hoy** para dispararlo a demanda.

**Pieza 6 — Mi ruta de hoy.** Menú *Ruteo de Visitas → Mi ruta de hoy*: lista de
las visitas del día del vendedor logueado, ordenadas por el recorrido, con
cliente, tipo de visita y motivo. Filtros Hoy / Mías / Generadas por ruteo.

> Mapa visual con la línea de ruta = pendiente (requiere token MapBox; se difirió).
> La lista ordenada + navegación por Google Maps cubre el uso diario sin costo.

## Campos nuevos en `res.partner`

| Campo | Descripción |
|---|---|
| `ruteo_is_located` | Tiene coordenadas válidas (no 0,0). Almacenado. |
| `ruteo_geo_status` | Estado: pendiente / ubicado / falló. |
| `ruteo_geo_pending` | Falta (re)ubicar tras un cambio de dirección. |
| `ruteo_geo_last_try` | Último intento de geolocalización. |
| `ruteo_geo_message` | Detalle del último resultado/error. |
| `ruteo_zona_id` / `ruteo_weekday` | Micro-zona y día de visita. |
| `ruteo_frequency_days` | Frecuencia de visita (días), según nivel. |
| `ruteo_last_visit` / `ruteo_next_visit_due` / `ruteo_is_due` | Seguimiento de visitas. |

## Filtros nuevos (búsqueda de contactos)

- **Sin ubicar en el mapa** — clientes de cartera todavía sin coordenadas.
- **Geo pendiente** — en cola del cron.
- **Geo fallida** — no se pudo ubicar (revisar dirección).
