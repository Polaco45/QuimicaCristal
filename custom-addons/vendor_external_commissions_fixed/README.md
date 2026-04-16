# Vendor External Commissions

Módulo para Odoo 18 que calcula y liquida comisiones de un vendedor externo con la siguiente lógica:

- Primera factura publicada o reactivación luego de 6 meses sin compras: 20% sobre subtotal sin impuestos.
- Facturas posteriores: 5% sobre subtotal sin impuestos.
- Las notas de crédito descuentan comisión con la misma tasa de la factura original.
- La liquidación se hace por facturas pendientes, no por clientes.

## Operativa sugerida

1. Instalar el módulo.
2. Verificar que las facturas de cliente tengan el vendedor correcto en el campo **Comercial / Vendedor**.
3. Publicar facturas normalmente.
4. Ir a **Contabilidad > Clientes > Comisiones externas**.
5. Crear una liquidación, elegir vendedor y fecha de corte.
6. Pulsar **Cargar pendientes**.
7. Revisar totales y confirmar la liquidación.

## Notas

- La base y la comisión se guardan en moneda de la compañía.
- Las notas de crédito sin factura origen quedan marcadas para revisión manual.
