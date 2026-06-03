# Cristal — Relevamiento Plan Control (`cristal_relevamiento`)

Módulo Odoo 18 para el relevamiento inicial presencial del Plan Control.

## Qué hace
- Crea el modelo **`cristal.relevamiento`** colgado de **`res.partner`** (el relevamiento
  pertenece al cliente; si la oportunidad se pierde, no se pierde el relevamiento).
- Puntero opcional al **`lead_id`** de origen.
- Pestaña **"Relevamiento"** en el Lead, visible desde la etapa *Relevamiento agendado*
  en adelante (anclado por `stage_id.sequence >= 3`, no por ID).
- Pestaña **"Relevamientos"** + botón inteligente en la ficha del cliente.
- **Rubros** = etiquetas hijas de "Rubros" (`res.partner.category`), multi-selección,
  precargadas desde la ficha del cliente y **sincronizadas** de vuelta al guardar.
- Líneas: productos que usa, muestras entregadas, **diagnóstico por sector 1-5** (interno,
  línea de base para el reporte de mejora a 3 meses).
- Catálogo de opciones (`cristal.relevamiento.opcion`) para los multi-select.
- Reporte PDF (QWeb) del relevamiento completo, con el bloque interno marcado.

## Instalación
1. Copiar la carpeta `cristal_relevamiento/` al addons-path (en la **dev** primero:
   `quimicacristal-finanzas-...dev.odoo.com`).
2. Activar modo desarrollador → Apps → Actualizar lista de aplicaciones.
3. Instalar **"Cristal — Relevamiento Plan Control"**.

## Dependencias
`crm`, `contacts`, `product` (todas estándar).

## Notas
- Si el Lead aún no tiene cliente (`partner_id`), la pestaña avisa que hay que asignarlo
  primero (el relevamiento se cuelga del cliente).
- Las automatizaciones (mover etapa al completar, tarea de seguimiento de muestra, flag de
  crédito por plazo ≠ contado, vencimiento del 20% OFF) se cargan aparte con `base.automation`
  una vez instalado el módulo.
