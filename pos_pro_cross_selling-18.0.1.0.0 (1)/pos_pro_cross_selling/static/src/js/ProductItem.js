/** @odoo-module **/

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { rpc }            from "@web/core/network/rpc";
import { patch }          from "@web/core/utils/patch";
import { CrossProduct }   from "@pos_pro_cross_selling/app/cross_product/cross_product";

patch(ProductScreen.prototype, {
    async addProductToOrder(product, options = {}) {
        // ­--- 1) Añadimos el producto con la lógica nativa de Odoo
        await super.addProductToOrder(product, options);

        // ­--- 2) Consultamos si el artículo tiene productos de cross-selling
        rpc("/web/dataset/call_kw/pos.cross.selling/get_cross_selling_products", {
            model:  "pos.cross.selling",
            method: "get_cross_selling_products",
            args:   [[], product.id],
            kwargs: {},
        }).then(async (result) => {
            if (result.length > 0) {
                // ­--- 3) Mostramos el popup con las sugerencias
                await this.dialog.add(CrossProduct, { product: result });
            }
        });
    },
});
