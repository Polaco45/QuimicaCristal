/** @odoo-module **/

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { rpc } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";
import { CrossProduct } from "@pos_pro_cross_selling/app/cross_product/cross_product";

patch(ProductScreen.prototype, {
    async addProductToOrder(product, options = {}) {
        // Agrega el producto normalmente usando la lógica nativa de Odoo
        await super.addProductToOrder(product, options);

        // Luego mostramos productos sugeridos si existen
        rpc('/web/dataset/call_kw/pos.cross.selling/get_cross_selling_products', {
            model: 'pos.cross.selling',
            method: 'get_cross_selling_products',
            args: [[], product.id],
            kwargs: {},
        }).then(async(result) => {
            if (result.length > 0) {
                await this.dialog.add(CrossProduct, {
                    product: result
                });
            }
        });
    },
});
