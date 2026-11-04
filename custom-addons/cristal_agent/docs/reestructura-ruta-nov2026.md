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

## Grupo 2 — Extensiones cortas (20-35 km), a decidir
Suman kilómetros al recorrido: solo convienen si el chofer las acepta o con pedido mínimo.
| Pueblo | Ramal | Distancia | Contactos |
|---|---|---|---|
| Almafuerte | Norte (RN36, después de Los Cóndores) | ~32 km pasando Berrotarán | 2 / 3 |
| Embalse | Norte (RN36 + RP5) | 27 km | 2 / 2 |
| Alpa Corral | Norte (sierra, desde Elena) | 33 km | 2 / 3 |
| Las Albahacas | Sur-Oeste (desde Achiras) | 32 km | 1 / 2 |
| La Cautiva | Sur-Oeste (desde Vicuña Mackenna) | 29 km | 2 / 2 |
| Washington | Sur-Oeste (entre Moldes y Vicuña Mackenna) | 21 km | 1 nuevo |
| Pascanas | Este (después de Chazón) | 23 km | 1 / 1 |

## Grupo 3 — Corredores nuevos (> 35 km), decisión de negocio
| Corredor | Pueblos | Contactos | Cómo |
|---|---|---|---|
| Norte → Río Tercero | Almafuerte, Río Tercero (ciudad grande) | 6 / 10 | Extender Norte A por RN36 (~45 km más). |
| Este → Canals | Canals, Viamonte | 5 / 6 | Extender Este B por RN8 pasando La Carlota (~45 km). |
| Sur-Este → Laboulaye | General Levalle, Laboulaye, Rio Bamba | 8 / 11 | Sur-Este es el circuito más chico (33 contactos): sumarle el corredor RN7 lo fortalece (~70 km más). |
| Sur profundo (RN35) | Del Campillo, Nicolás Bruzzone, Mattaldi, Jovita, Villa Valeria, Huinca Renancó, Villa Huidobro | ~17 / 22 | Está a 140-190 km: sería un 5.º circuito y la rotación pasaría a cada 5 semanas. |

Fuera de alcance (Córdoba capital, CABA, otras provincias, Villa María/Río Tercero norte lejano por otros
ramales, etc.) quedan como fuera de zona.
