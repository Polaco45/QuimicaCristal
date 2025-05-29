/** @odoo-module **/

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { rpc }          from "@web/core/network/rpc";
import { patch }        from "@web/core/utils/patch";
import { CrossProduct } from "@pos_pro_cross_selling/app/cross_product/cross_product";

patch(ProductScreen.prototype, {
    async addProductToOrder(product, options = {}) {
        // 1) lógica nativa: añade el producto al ticket
        await super.addProductToOrder(product, options);

        // 2) obtener tarifa y cliente actuales del pedido
        const order     = this.currentOrder;
        const pricelist = order.pricelist;          // objeto pricelist
        const partner   = order.get_partner();      // puede ser null

        // 3) pedir productos sugeridos enviando contexto
        rpc("/web/dataset/call_kw/pos.cross.selling/get_cross_selling_products", {
            model:  "pos.cross.selling",
            method: "get_cross_selling_products",
            args:   [[], product.id],
            // ←─────────────  contexto que tu método Python espera ──────────────→
            context: {
                pricelist:  pricelist && pricelist.id,
                partner_id: partner   && partner.id,
            },
        }).then(async (result) => {
            if (result.length) {
                await this.dialog.add(CrossProduct, { product: result });
            }
        });
    },
});
