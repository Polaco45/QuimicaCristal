/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { rpc }   from "@web/core/network/rpc";
import ProductScreen from "@point_of_sale/app/screens/product_screen/product_screen";
import CrossProduct  from "@pos_pro_cross_selling/app/cross_product/cross_product";

/**
 * Parcheamos el método que se dispara al hacer clic en un producto.
 */
patch(ProductScreen.prototype, {
    async addProductToOrder(product, options = {}) {

        /* 1 ⸺ lógica nativa: agrega el producto a la orden */
        await super.addProductToOrder(product, options);

        /* 2 ⸺ si existe configuración de cross-selling pedimos los sugeridos */
        const order     = this.currentOrder;
        const pricelist = order.pricelist;          // lista activa
        const partner   = order.get_partner();      // cliente (puede ser null)

        const crossProducts = await rpc({
            model:  "pos.cross.selling",
            method: "get_cross_selling_products",
            args:   [[], product.id],
            context: {
                pricelist:  pricelist && pricelist.id,
                partner_id: partner   && partner.id,
            },
        });

        if (crossProducts.length) {
            await this.dialog.add(CrossProduct, { product: crossProducts });
        }
    },
});
