# Reestructura de la ruta del camión — 04/11/2026

Relevamiento: 226 ciudades distintas entre contactos y leads de Odoo; 170 quedan hoy fuera de Río Cuarto y
de los 4 circuitos. Cada pueblo candidato se ubicó en el mapa (OpenStreetMap, corregido a mano donde el
geocoder confundía calles de Córdoba capital) y se midió su distancia al tramo de ruta más cercano de cada ramal.
Ramales: Norte A (RN36: Espinillo → Berrotarán), Norte B (Chucul → Dalmacio Vélez), Sur-Oeste A (Holmberg →
Chaján), Sur-Oeste B (Malena → Vicuña Mackenna), Este A (Charras → Chazón), Este B (Las Acequias → La Carlota),
Sur-Este (San Basilio → Monte de los Gauchos).

Ojo: un pueblo "opcional" se comporta igual que uno normal para Claudio; si está en un circuito, Claudio le
confirma al cliente que el camión pasa. Por eso solo se suma lo que el camión va a cubrir.

## Grupo 1 — De paso (≤ 20 km de la ruta, con contactos) · APLICADO 04/11
| Pueblo | Circuito | Distancia | Contactos (mayoristas / leads) |
|---|---|---|---|
| Río de los Sauces | Norte (desvío opcional) | 19 km de RN36 entre Elena y Berrotarán | 4 / 5 (3 nuevos) |
| Los Cóndores | Norte (desvío opcional) | 18 km después de Berrotarán por RN36 | 2 / 2 |
| Santa Eufemia | Este | entre Chazón y La Carlota | 1 / 1 |
| Bulnes | Sur-Oeste (desvío opcional) | 14 km, entre Sampacho y Coronel Moldes | 1 nuevo |
Se reasignaron 9 contactos a su circuito y se actualizó la KB 102 (lista de localidades por circuito).
Las placas y campañas que genera el cron D-7 ya los incluyen.

## Regla de zona (Joaco, 04/11/2026)
Ningún pueblo del recorrido puede quedar a más de **120 km de Río Cuarto en línea recta**
(centro -33.1232, -64.3493; distancia haversine). Lo que pase ese radio es fuera de zona, aunque
quede cerca de un ramal. Antes de sumar cualquier pueblo nuevo, medirlo.

## Grupo 2 — Extensiones cortas (20-35 km) · APLICADO 04/11 (menos Pascanas)
Todos como desvío opcional. Se reasignaron 19 contactos y se actualizó la KB 102.
| Pueblo | Ramal | Desvío | Km a Río Cuarto | Estado |
|---|---|---|---|---|
| Almafuerte | Norte (RN36, después de Los Cóndores) | ~32 km pasando Berrotarán | 104 | Sumado (town 39) |
| Embalse | Norte (RN36 + RP5) | 27 km | 102 | Sumado (town 40) |
| Alpa Corral | Norte (sierra, desde Elena) | 33 km | 59 | Sumado (town 41) |
| Las Albahacas | Sur-Oeste (desde Achiras) | 32 km | 53 | Sumado (town 42) |
| La Cautiva | Sur-Oeste (desde Vicuña Mackenna) | 29 km | 98 | Sumado (town 43) |
| Washington | Sur-Oeste (entre Moldes y Vicuña Mackenna) | 21 km | 89 | Sumado (town 44) |
| Pascanas | Este (después de Chazón) | 23 km | **122** | **Descartado por la regla de 120 km** |

## Grupo 3 — Corredores nuevos, filtrados por la regla de 120 km
| Corredor | Pueblos | Km a Río Cuarto | Estado |
|---|---|---|---|
| Norte → Río Tercero | Río Tercero (ciudad grande, 4 / 7 contactos) | 108 | Entra en el radio. A decidir. |
| Sur-Este → RN7 | General Levalle, Rio Bamba | 106 / 118 | Entran en el radio. A decidir; fortalecen al Sur-Este. |
| Sur-Este → Laboulaye | Laboulaye | 143 | Fuera de zona. |
| Este → Canals | Canals, Viamonte | 145 / 135 | Fuera de zona. |
| Sur profundo (RN35) | Del Campillo, Mattaldi, Jovita, Villa Valeria, Huinca Renancó, Villa Huidobro | 140-192 | Fuera de zona: se descarta el 5.º circuito. |

Fuera de alcance (Córdoba capital, CABA, otras provincias, Villa María/Río Tercero norte lejano por otros
ramales, etc.) quedan como fuera de zona.
