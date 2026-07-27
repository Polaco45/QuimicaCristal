# Cristal — Ruteo de Visitas (`cristal_ruteo`)

Planificador de rutas de visita para la fuerza de venta de calle, estilo **PJP
(Plan de Jornada Permanente)** de distribuidora FMCG. Se apoya en el motor de
valor que ya calcula `cristal_agent` (nivel, compras, churn, zona macro) y agrega
la capa geográfica + de ruteo.

## Roadmap (pieza por pieza)

1. **Geolocalización automática** ✅ *(este release — v18.0.1.0.0)*
2. Micro-zonas de ruta (`cristal.ruta.zona`) con día de la semana asignado
3. Frecuencia por valor (oro=7d / plata=15d / bronce=30d) + próxima visita
4. Score de prioridad de visita (etapa CRM + días sin comprar + churn + nivel)
5. Generador de ruta diaria (cron) → actividades "Visitar Institución" numeradas
6. Vistas "Mi ruta de hoy" (lista + mapa nativo) y tablero de zonas

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

**Proveedor:** usa el geocodificador configurado en Ajustes (por defecto
OpenStreetMap / Nominatim, sin costo ni API key). El módulo depende de
`base_geolocalize`.

## Campos nuevos en `res.partner`

| Campo | Descripción |
|---|---|
| `ruteo_is_located` | Tiene coordenadas válidas (no 0,0). Almacenado. |
| `ruteo_geo_status` | Estado: pendiente / ubicado / falló. |
| `ruteo_geo_pending` | Falta (re)ubicar tras un cambio de dirección. |
| `ruteo_geo_last_try` | Último intento de geolocalización. |
| `ruteo_geo_message` | Detalle del último resultado/error. |

## Filtros nuevos (búsqueda de contactos)

- **Sin ubicar en el mapa** — clientes de cartera todavía sin coordenadas.
- **Geo pendiente** — en cola del cron.
- **Geo fallida** — no se pudo ubicar (revisar dirección).
