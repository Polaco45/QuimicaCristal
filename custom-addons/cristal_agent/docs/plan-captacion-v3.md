# Captación mayorista v3 — decisiones de Joaco (06/11/2026) y plan

Principio de Joaco: mucho movimiento en pauta y orgánico, todo automático e inteligente. El motor
ejecuta solo la mayoría de los cambios y solo propone los contundentes. Optimizar recursos: gastar
lo mínimo en créditos y pauta, sin bajar la calidad.

## Decisiones por punto
| # | Punto | Decisión |
|---|---|---|
| 1 | Placas por salida | Seguir igual (automático). |
| 2 | Video por salida | Automático con Higgsfield. Se cargan créditos; optimizar costo. |
| 3 | Creativos Río Cuarto | Optimización constante y automática. |
| 4 | Orgánico | Más volumen: al menos una historia por día + feed mayorista; se publica solo. |
| 5 | Reels | Subir los mismos videos de pauta como reels, probar variantes, aprender y crear nuevos. |
| 6 | Campaña por salida | B: presupuesto según el peso de cada zona. «Se está gastando mucho». |
| 7 | Río Cuarto continua | A: ejecuta solo los cambios chicos y avisa. |
| 8 | Remarketing | No por ahora: preferir orgánico. Queda en borrador. |
| 9 | Público similar | A: se refresca solo cada lunes con los que compraron. |
| 10 | Escalado | Solo si hay ventas reales atribuidas que lo respalden. |
| 11 | Aviso de paso por WhatsApp | Sale solo a todos los contactos de la zona (menos «No contactar»), D-6 a D-2, hasta 100 por día. Necesita la plantilla ruta_aviso_paso aprobada por Meta (hoy en borrador). |
| 12 | Mensajes y comentarios de IG/FB | A: respuesta automática que lleva a WhatsApp con código de origen. |
| 13 | Prospección en frío | No se hace. |
| 14 | Referidos | B: campaña mensual o quincenal a clientes activos (plantilla de WhatsApp a aprobar). |
| 15 | Código de origen | A: mensaje prellenado con código en cada anuncio nuevo y Claudio pregunta cómo nos conoció cuando no hay código (`set_origin`, v1.61). |
| 16 | Perfil de Google | A: el orgánico también se publica en Google Business con Metricool (falta conectar el perfil en Metricool). |

## Autonomía nueva (nivel 2)
Ejecuta solo y avisa en el canal 969: pausar anuncios perdedores, mover hasta 20 % entre anuncios o
conjuntos, rotar creativos, crear anuncios nuevos del ángulo ganador, publicar orgánico, historias y
reels, cargar públicos, subir o bajar hasta 20 % un presupuesto dentro del tope.
Propone y espera «dale»: cambios de presupuesto de más del 20 %, subir el tope semanal, campañas de
un tipo nuevo, pausar una campaña entera, gastar créditos por encima del presupuesto mensual.

## Presupuesto (6B y 10)
- Por salida: $250 por contacto mayorista de la zona, mínimo $10.000 y máximo $30.000 por salida
  (antes $50.000 fijo). Norte ≈ $30.000, Sur-Oeste ≈ $30.000, Este ≈ $15.000, Sur-Este ≈ $10.000.
- Tope semanal total: $90.000 (antes $120.000).
- Escalado: +20 % semanal solo si dos semanas seguidas el costo por comprador nuevo atribuido en
  Odoo es ≤ 25 % del ticket del primer pedido y hay al menos 3 compras atribuidas. Nunca por encima
  del tope sin «dale».

## Motor creativo
**Odoo (gratis, determinístico):**
- Placas 4:5 por salida (ya existe, D-7).
- Historias 9:16, una por día, generadas con el orgánico del mes: salida de esta semana, cierre de
  preventa (miércoles), combo, fábrica, margen, clientes. Copy en la descripción del adjunto.
- Placas de Río Cuarto rotativas: cada 14 días, una por ángulo (FABRICA, MARGEN, PRUEBA_SOCIAL,
  PRODUCTO), sin pueblos. Copy en la descripción del adjunto.
**Tareas de Claude (IA y APIs):**
- `pauta-mayorista-semanal` (lunes): analista + ejecutor nivel 2: resultados, pausa perdedores,
  rota creativos de Río Cuarto con las placas nuevas, refresca el público similar, aplica la regla de
  escalado, programa el orgánico y las historias de los próximos 8 días en Metricool (publicados) y
  mira qué orgánico rinde para ajustar ángulos.
- `pauta-ruta-por-salida` (martes y jueves): campaña por salida con presupuesto por zona, urgencia
  D-2 y video de la salida cuando existe.
- `video-semanal` (miércoles): videos con Higgsfield optimizando créditos (abajo).

## Videos baratos y buenos
- Video madre genérico por ángulo, sin pueblos: 15 s a 720p con la voz clonada de Joaco y su imagen
  (≈ 105 créditos). Sirve un mes para todas las zonas, Río Cuarto y reels. Dos nuevos por mes.
- Gancho por salida: 5 s que nombran los pueblos y la fecha (≈ 35 créditos) unido al video madre
  con ffmpeg (gratis). Cuatro por mes.
- Variantes de reels: recortes, subtítulos y orden distinto del material existente con ffmpeg
  (gratis). Una prueba nueva por semana; gana la que más retención y conversaciones da.
- Presupuesto: ≈ 400 créditos por mes; la tarea consulta el saldo antes de generar y avisa si no
  alcanza. Siempre preflight de costo; 480p solo para probar guiones.

## Qué depende de Joaco
- Regularizar el pago de Claude (las tareas programadas se cortaron el 05/11 por eso).
- Cargar créditos de Higgsfield (≈ 400 por mes).
- Habilitar cristal.agent.creative y cristal.agent.experiment en MCP Model Access (aprendizaje).
