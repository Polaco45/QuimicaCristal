MRP Vendor BoM Cost - Odoo 18

Qué hace
---------
Agrega:
1) Un botón en el formulario de producto: "Costo proveedor desde LdM"
2) Una acción masiva en la lista de productos: "Calcular costo proveedor desde LdM"

Cómo calcula
------------
- Toma la Lista de Materiales del producto.
- Para cada componente usa el PRIMER proveedor válido de la pestaña Compra.
- Usa su precio y le resta el descuento si existe.
- Convierte moneda y unidad de medida cuando corresponde.
- Guarda el resultado final en el costo del producto (standard_price).

Instalación
-----------
1. Subir la carpeta mrp_vendor_bom_cost a custom_addons.
2. Actualizar lista de aplicaciones.
3. Instalar el módulo "MRP Vendor BoM Cost".

Importante
----------
- El producto final debe tener una sola variante.
- Debe tener Lista de Materiales.
- Si algún componente no tiene proveedor válido, lanza error para no calcular mal.
