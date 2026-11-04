# Cierre de la automatización mayorista — plan 1.59 (04/11/2026)

Pedido de Joaco: "seguimos la automatización completa del mayorista". Fases 0-3 hechas,
Fase 4 hecha en ruta (contenido D-7, campaña Este, tarea semanal, público de remarketing).
Lo que falta del organigrama, todo en un solo paquete planificado antes de tocar nada.

## Qué falta y cómo se cierra

| # | Ítem | Qué se hace | Dónde |
|---|---|---|---|
| E5 / 22 | Contenido orgánico mensual | El día 25 Odoo genera el calendario del mes siguiente: 2 posteos por semana (martes y viernes), una placa por ángulo con datos reales (fábrica, margen, combos activos, cantidad real de negocios clientes, calendario de salidas del camión) y su texto. La tarea semanal los sube a Metricool **para revisión** (no publica solo). | Odoo 1.59 + tarea semanal |
| E6 | Aprendizaje | La tarea semanal registra cada propuesta como experimento (hipótesis, métrica, evaluar a 7 días), carga resultados de Meta en cada creativo por `meta_ad_id`, y anota lo aprendido en la KB «Pauta: aprendizajes». | Tarea semanal + conector (habilitar creativos y experimentos) |
| 25 | Revisión mensual automática (Fase 5) | El día 1 Odoo arma la revisión del mes anterior y la publica en el canal 969: ventas mayoristas, embudo por origen, etapas contra el mes anterior, motor de acciones con su control (¿las acciones venden más que el grupo sin contacto?), salidas del camión, ángulos de pauta, costo de Claudio, y recomendaciones con reglas fijas. | Odoo 1.59 |
| 24 | Remarketing | Campaña en Meta al público «cotizados sin comprar» (sincronizado cada lunes), $20.000 por semana dentro del tope de $120.000, dos ángulos sin nombres de pueblos (PRUEBA_SOCIAL y REGALO/combos). Queda **en pausa** hasta el «dale» de Joaco. | Meta |
| 16 | Reseñas de Google | Buscar el link de reseña del perfil de Química Cristal. Si existe: Claudio lo manda cuando la encuesta responde «Bien» (KB 110). | KB |
| 23 | Ingesta de Lead Ads / IG / web | No aplica hoy: todos los anuncios van a WhatsApp, que ya entra a Odoo con código de origen. Se revisa si aparece un formulario. | — |

## Diseño de 1.59 (cristal_agent)

**Creativo:** formato nuevo `organico`, campos `planned_date` (fecha de publicación) y
`metricool_id`, estado nuevo `scheduled` (programado en Metricool).

**Generador orgánico** (`cristal.agent.pauta.generate_organic_month(mes)`):
- Fechas: martes y viernes del mes. Rotación de ángulos: FABRICA, PRODUCTO, MARGEN,
  LOGISTICA, PRUEBA_SOCIAL, PRODUCTO, … (PRODUCTO recorre las ofertas activas con combo).
- Datos: PRUEBA_SOCIAL usa la cantidad real de negocios activos (redondeada hacia abajo a
  la decena, solo si son ≥ 20); LOGISTICA lista las salidas del mes por nombre de circuito
  y fecha (no nombra pueblos); PRODUCTO usa nombre y descripción de la oferta.
- Idempotente por fecha. Aviso en el canal 969 con la lista.
- Cron diario: corre el día `pauta_organic_day` (25) para el mes siguiente.

**Revisión mensual** (`cristal.agent.monthly.review`, una fila por mes, HTML + JSON):
- Reglas de recomendación: acción del motor con ≥ 30 contactos que no vende más que su
  control → revisar/pausar; cupo diario lleno en ≥ la mitad de los días → subir cupo;
  en riesgo + dormidos crecen > 10 % → reforzar reactivación; salida con < 3 pedidos →
  revisar zona/pauta; ángulo ganador por costo por conversación (≥ 2 creativos con
  resultado); costo de Claudio > 80 % del tope mensual.
- Cron diario: corre el día 1, una vez por mes. Menú Ciclo de vida → Revisión mensual.

**Config:** `pauta_organic_enabled` (sí), `pauta_organic_day` (25),
`monthly_review_enabled` (sí).

**Autotest:** 57 orgánico (placas públicas, fechas martes/viernes del mes siguiente,
idempotente), 58 revisión mensual (arma el HTML, guarda snapshot, recomendaciones).

## Orden de ejecución
1. Código 1.59 + autotest → staging (`pruebaAle`) → build verde → main.
2. Conector: habilitar `cristal.agent.creative` y `cristal.agent.experiment` (leer, crear,
   editar) en `mcp.model.access`. KB «Pauta: aprendizajes».
3. Generar el orgánico de noviembre/diciembre en prod y subir los borradores a Metricool
   para revisión.
4. Placas de remarketing con el generador → campaña en pausa en Meta.
5. Link de reseñas → KB 110.
6. Tarea semanal: prompt con orgánico + experimentos + resultados por creativo.
7. Doc del plan, memoria.

## Qué NO hace
Nada se publica solo: el orgánico queda para revisión en Metricool y el remarketing en
pausa. No hay envíos masivos de WhatsApp. No se toca el presupuesto de campañas activas.
