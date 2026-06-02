# Quimica Cristal · Reporte Mensual Plan Control

Módulo de Odoo 18 que genera y envía automáticamente reportes mensuales de consumo a los clientes del **Plan Control** de Quimica Cristal.

## Qué hace

* **Cron mensual automático** el día 1 de cada mes a las 8 AM:
  - Busca todos los partners con etiqueta `Plan Control`
  - Para cada uno genera el PDF del mes anterior (datos reales de Odoo)
  - Envía el PDF por email
  - Saltea los que no tienen facturas en el período

* **Wizard de generación manual** ("Generar reporte manual"):
  - Seleccionás el cliente y el período (año/mes)
  - Decidís si solo descargar el PDF o también enviar por email
  - Si ya existe el reporte de ese período, lo regenera

## Reglas de cálculo

* **Sobre el TOTAL con IVA** (`amount_total`), NO sobre el subtotal
* **Notas de crédito (`out_refund`) RESTAN del total**
* Solo facturas/NC `state = 'posted'`
* Solo `company_id = 1` (la única operativa)
* Excluye partners internos (Sergio, Adrián, Joaco, etc.)

## Categorización de productos

Por `product.template.categ_id` (no por keywords). Las 53 categorías del catálogo Odoo se mapean a **5 macro categorías**:

| Macro categoría (reporte) | Visualización | Categorías Odoo incluidas |
|---|---|---|
| **Líquidos** | Destacada | Detergente, Desengrasante, Limpiador Desinf Desod, Linea Lavandería, Perfumeria, Quimicos p/Piletas, Bases Concentradas, Cloro, Lavandina, Mantenimiento de pisos, Liquidos, Aerosoles, Aromatizantes, Limpia Vidrios |
| **Papeles** | Destacada | Servilletas y Papel Higiénico |
| **Bolsas** | Destacada | Bolsas |
| **Accesorios** | Secundaria | Baldes, Mopas, Cabos, Cestos, Dispensers, Escobillones, Esponjas, Gatillos, Guantes, Lampazos, Palas, Plumeros, Secadores, Trapos, Alfombras, Envases |
| **Varios** | Secundaria | Accesorios p/piletas, Bazar, Casa y Jardin, Linea Automotor, Combos, Consumo Masivo |

Cualquier `product.category` NO mapeada cae automáticamente en "Varios" (no rompe nada).

## Multi-sucursal

El reporte detecta automáticamente si un cliente tiene múltiples `partner_shipping_id`:

* **Single-dirección**: 1 página con todos los datos consolidados
* **Multi-sucursal**: 1 página general + 1 página por cada sucursal con compras del mes

## Instalación

1. Copiar el directorio `quimica_cristal_reporte_mensual` al `addons_path` de Odoo
2. Actualizar lista de apps: `Settings > Apps > Update Apps List`
3. Buscar "Reporte Mensual Plan Control" e instalar
4. (Opcional) Marcar la etiqueta `Plan Control` (creada automáticamente al instalar) a los clientes que tienen que recibir el reporte

## Estructura del módulo

```
quimica_cristal_reporte_mensual/
├── __init__.py
├── __manifest__.py
├── README.md
├── data/
│   ├── cron_data.xml                       # Cron mensual día 1 a las 8 AM
│   ├── mail_template_data.xml              # Template del email con KPIs
│   └── res_partner_category_data.xml       # Etiqueta "Plan Control"
├── models/
│   ├── __init__.py
│   └── quimica_cristal_reporte_mensual.py  # Modelos: reporte + sucursal + line
├── report/
│   ├── reporte_report.xml                  # Declaración del action_report
│   └── reporte_template.xml                # Template QWeb del PDF
├── security/
│   └── ir.model.access.csv                 # Permisos
├── views/
│   ├── menu.xml                            # Menús
│   └── reporte_mensual_views.xml           # Vistas form/list del modelo
└── wizards/
    ├── __init__.py
    ├── reporte_descarga_wizard.py          # Wizard de descarga manual
    └── wizard_views.xml                    # Vista del wizard
```

## Observaciones manuales

Tanto el reporte como cada sucursal tienen un campo `observation` opcional manual. Por defecto está vacío y el cron NUNCA escribe ahí. Si Joaco quiere agregar una nota a un reporte específico, lo edita desde la UI antes de enviar. Si el campo tiene contenido, aparece en el PDF; si está vacío, no aparece el bloque.

## Tests sugeridos antes de subir a producción

1. **Generar reporte de Dill SRL mayo 2026**. Verificar que da exactamente:
   * Total consolidado: `$3.037.370,00`
   * Facturas: 17
   * Notas de crédito restadas: 1
   * Sucursales: 4 (Restaurante Golf, Fishy, Parla, Parla 2)
   * Restaurante Golf: `$1.144.230` (37,67%)
   * Fishy: `$839.670` (27,64%)
   * Parla: `$699.990` (23,05%, incluye 1 NC restada)
   * Parla 2: `$353.480` (11,64%)

2. **Generar reporte de un cliente single-dirección** (cualquiera que tenga solo una `partner_shipping_id` con compras). Verificar que genera 1 sola página.

3. **Generar reporte de un cliente SIN facturas en el período**. Verificar que el reporte queda vacío pero no falla.

4. **Configurar etiqueta "Plan Control"** a 1 cliente de prueba y ejecutar manualmente el cron desde Settings > Technical > Scheduled Actions. Verificar que se genera y envía.

## Autor

Joaquín Ramello — Quimica Cristal (Crilim S.A.S.)
Río Cuarto, Córdoba, Argentina
cristal@quimicacristal.com.ar
