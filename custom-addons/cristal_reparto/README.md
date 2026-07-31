# Cristal — Reparto (`cristal_reparto`)

Organiza la **vuelta de reparto del día** y avisa por WhatsApp al próximo cliente.

## Flujo

1. Se **valida la SM/PACK** → la orden de entrega (SM/OUT) río abajo entra sola a
   la **vuelta de reparto de hoy** (`cristal.reparto`).
2. El repartidor abre la vuelta, toca **Ordenar por cercanía** (vecino más cercano
   desde el local, Av. San Martín 2350) y **reordena** arrastrando si quiere.
3. **Iniciar reparto**. Marca **Entregado** cada pedido (valida la OUT). Ahí:
   - Al **próximo** pendiente de la lista le llega el WhatsApp *"sos el próximo"*.
   - El avance se actualiza: entregadas / total, última y próxima entrega.

## Roadmap

- **Pieza A** ✅ *(v18.0.1.0.0)*: modelo de vuelta, auto-alta al validar la PACK,
  lista reordenable, marcar entregado, tracking. El aviso de WhatsApp está **stub**
  (por ahora solo loguea a quién avisaría).
- **Pieza B**: envío real del WhatsApp *"sos el próximo"* con plantilla dedicada
  (`reparto_proximo`, a aprobar en Meta una sola vez).

## Notas

- Depende de `cristal_ruteo` (reusa el geocodificador georef y el vecino-más-cercano)
  y de `whatsapp`.
- El mensaje del "pedido en camino" (al validar la PACK) **NO** lo maneja este
  módulo — ya existe aparte.
- Local (punto de partida del orden): Av. San Martín 2350, Río Cuarto
  (-33.1159928, -64.3788190).
