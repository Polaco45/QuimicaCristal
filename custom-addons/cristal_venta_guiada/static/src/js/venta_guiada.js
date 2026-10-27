/** @odoo-module */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

// Venta guiada: cada producto que se carga en un ticket de consumidor final
// muestra una tarjeta con UNA sugerencia (combo, tamaño mayor o complemento).
// La tarjeta no bloquea: si el vendedor sigue cargando, se reemplaza sola.

const KIND_TITLE = {
    combo: "Combo",
    size: "Tamaño más conveniente",
    complement: "Se lleva junto",
    category: "Sumale",
    manual: "Sumale",
    checkout: "Para cerrar",
};

function cleanName(product) {
    return (product?.display_name || "").replace(/^\[[^\]]*\]\s*/, "");
}

function isLoose(line) {
    return !line.combo_parent_id && !line.combo_line_ids?.length;
}

patch(PosStore.prototype, {
    async setup() {
        this.cristalVg = { card: null };
        return await super.setup(...arguments);
    },

    async afterProcessServerData() {
        const res = await super.afterProcessServerData(...arguments);
        const vg = this.cristalVgConfig();
        const categ = vg?.start_categ_id && this.models["pos.category"].get(vg.start_categ_id);
        if (categ) {
            this.selectedCategory = categ;
        }
        return res;
    },

    cristalVgConfig() {
        const vg = this.session?._cristal_vg;
        return vg?.enabled ? vg : null;
    },

    cristalVgActive(order) {
        const vg = this.cristalVgConfig();
        if (!vg || !order || order.finalized) {
            return false;
        }
        const fp = order.fiscal_position_id?.id;
        return !vg.cf_fp_ids?.length || !fp || vg.cf_fp_ids.includes(fp);
    },

    cristalVgState(order) {
        if (!order.uiState.cristalVg) {
            order.uiState.cristalVg = { shown: [], checkout: false };
        }
        return order.uiState.cristalVg;
    },

    cristalVgLog(order, event) {
        this.data.silentCall("cristal.vg.event", "log_events", [
            [{ config_id: this.config.id, order_uuid: order.uuid, ...event }],
        ]);
    },

    cristalVgFormat(amount) {
        return this.env.utils.formatCurrency(amount);
    },

    async addLineToCurrentOrder(vals, opts = {}, configure = true) {
        const line = await super.addLineToCurrentOrder(...arguments);
        if (configure && !opts.cristalVgSkip && line) {
            try {
                this.cristalVgAfterAdd(line);
            } catch (error) {
                console.warn("Venta guiada:", error);
            }
        }
        return line;
    },

    // Mira el ticket y elige qué sugerir para el producto recién cargado.
    cristalVgAfterAdd(line) {
        const order = this.get_order();
        const product = line.product_id;
        this.cristalVg.card = null;
        if (!this.cristalVgActive(order) || !product || product.isCombo()) {
            return;
        }
        const vg = this.cristalVgConfig();
        const state = this.cristalVgState(order);
        const inCart = new Set(order.lines.map((l) => l.product_id?.id));

        // 1) ¿Con esto ya está a mitad de camino (o completo) de un combo?
        const loose = {};
        for (const l of order.lines.filter(isLoose)) {
            loose[l.product_id.id] = (loose[l.product_id.id] || 0) + l.get_quantity();
        }
        // Precio suelto real: lo que ya está en el ticket más el más barato de lo que falta.
        const priceOf = (pid) => this.models["product.product"].get(pid)?.get_price(order.pricelist_id, 1) || 0;
        const slotPrice = (slot) => {
            const prices = slot.filter((id) => this.models["product.product"].get(id)).map(priceOf);
            return prices.length ? Math.min(...prices) : 0;
        };
        const checkoutId = vg.checkout?.product_id;
        let best = null;
        for (const combo of vg.combos || []) {
            if (!this.models["product.product"].get(combo.product_id)) {
                continue;
            }
            const avail = { ...loose };
            const matched = [];
            const missing = [];
            for (const slot of combo.slots) {
                const pid = slot.find((id) => avail[id] > 0);
                if (pid) {
                    avail[pid] -= 1;
                    matched.push(pid);
                } else {
                    missing.push(slot);
                }
            }
            const key = `combo-${combo.product_id}-${matched.length}`;
            if (!matched.includes(product.id) || matched.length * 2 < combo.slots.length) {
                continue;
            }
            const loosePrice =
                matched.reduce((sum, pid) => sum + priceOf(pid), 0) +
                missing.reduce((sum, slot) => sum + slotPrice(slot), 0);
            if (state.shown.includes(key) || loosePrice <= combo.price) {
                continue;
            }
            const ratio = matched.length / combo.slots.length;
            const saving = loosePrice - combo.price;
            if (!best || ratio > best.ratio || (ratio === best.ratio && saving > best.saving)) {
                best = { combo, matched, missing, key, ratio, saving, loosePrice };
            }
        }
        if (best) {
            const { combo, matched, missing, key, saving, loosePrice } = best;
            let text;
            if (combo.product_id === checkoutId) {
                text = missing.length
                    ? _t("Llevando otro (%(items)s) se lleva los 2 por %(price)s.", {
                          items: (vg.checkout.items || []).join(", "),
                          price: this.cristalVgFormat(combo.price),
                      })
                    : _t("Lleva 2 de la promo: cobralos juntos a %(price)s y ahorra %(saving)s.", {
                          price: this.cristalVgFormat(combo.price),
                          saving: this.cristalVgFormat(saving),
                      });
            } else if (!missing.length) {
                text = _t("Ya lleva todo el %(name)s. Cobralo como combo: suelto %(loose)s, combo %(price)s. Ahorra %(saving)s.", {
                    name: combo.name,
                    loose: this.cristalVgFormat(loosePrice),
                    price: this.cristalVgFormat(combo.price),
                    saving: this.cristalVgFormat(saving),
                });
            } else {
                const names = missing
                    .slice(0, 2)
                    .map((slot) => cleanName(this.models["product.product"].get(slot[0])))
                    .filter(Boolean);
                const more = missing.length > 2 ? _t(" y %s más", missing.length - 2) : "";
                text = _t("Sumando %(missing)s%(more)s se lleva el %(name)s a %(price)s (suelto %(loose)s). Ahorra %(saving)s.", {
                    missing: names.join(", "),
                    more,
                    name: combo.name,
                    price: this.cristalVgFormat(combo.price),
                    loose: this.cristalVgFormat(loosePrice),
                    saving: this.cristalVgFormat(saving),
                });
            }
            state.shown.push(key);
            this.cristalVg.card = {
                kind: "combo",
                title: KIND_TITLE.combo,
                text,
                triggerId: product.id,
                productId: combo.product_id,
                matched,
                orderUuid: order.uuid,
                amount: combo.price,
            };
            this.cristalVgLog(order, { trigger_product_id: product.id, product_id: combo.product_id, kind: "combo" });
            return;
        }

        // 2) Sugerencia calculada para este producto (tamaño mayor, complemento, respaldo)
        for (const [pid, kind, text] of vg.suggestions?.[product.id] || []) {
            const key = `${product.id}-${pid}`;
            const suggested = this.models["product.product"].get(pid);
            if (!suggested || inCart.has(pid) || state.shown.includes(key)) {
                continue;
            }
            state.shown.push(key);
            this.cristalVg.card = {
                kind,
                title: KIND_TITLE[kind] || KIND_TITLE.manual,
                text,
                triggerId: product.id,
                productId: pid,
                orderUuid: order.uuid,
                amount: suggested.get_price(order.pricelist_id, 1),
            };
            this.cristalVgLog(order, { trigger_product_id: product.id, product_id: pid, kind });
            return;
        }

        // 3) Sin otra sugerencia y con 2 productos o más: anunciar la promo de caja.
        if (order.lines.filter(isLoose).length >= 2) {
            this.cristalVgShowCheckout(order);
        }
    },

    async cristalVgAccept() {
        const card = this.cristalVg.card;
        const order = this.get_order();
        this.cristalVg.card = null;
        if (!card || !order || order.uuid !== card.orderUuid) {
            return;
        }
        const product = this.models["product.product"].get(card.productId);
        if (!product) {
            return;
        }
        if (card.kind === "combo" || card.kind === "checkout") {
            // Odoo abre su elección de aromas/colores; si se cancela, no se toca nada.
            const comboLine = await this.addLineToCurrentOrder({ product_id: product }, { cristalVgSkip: true });
            if (!comboLine) {
                return;
            }
            for (const pid of card.matched) {
                const l = order.lines.find((x) => x.product_id?.id === pid && isLoose(x));
                if (!l) {
                    continue;
                }
                if (l.get_quantity() > 1) {
                    l.set_quantity(l.get_quantity() - 1);
                } else {
                    order.removeOrderline(l);
                }
            }
            this.cristalVgLog(order, {
                trigger_product_id: card.triggerId,
                product_id: card.productId,
                kind: card.kind,
                accepted: true,
                amount: card.amount,
            });
            return;
        }
        this.cristalVgLog(order, {
            trigger_product_id: card.triggerId,
            product_id: card.productId,
            kind: card.kind,
            accepted: true,
            amount: card.amount,
        });
        // La sugerencia ya es una variante concreta: se agrega sin pedir presentación/aroma.
        // Lo agregado también es un producto cargado: puede traer su propia sugerencia.
        const line = await this.addLineToCurrentOrder({ product_id: product }, {}, false);
        if (line) {
            this.cristalVgAfterAdd(line);
        }
    },

    cristalVgDismiss() {
        this.cristalVg.card = null;
    },

    // Promo de caja (2 por $X): una sola vez por ticket. Se anuncia mientras se carga,
    // cuando no hay otra sugerencia, y si no se anunció, al ir a cobrar.
    cristalVgShowCheckout(order) {
        const vg = this.cristalVgConfig();
        const promo = vg?.checkout && this.models["product.product"].get(vg.checkout.product_id);
        const state = this.cristalVgState(order);
        if (!promo || state.checkout || order.lines.some((l) => l.product_id?.id === promo.id)) {
            return false;
        }
        state.checkout = true;
        this.cristalVg.card = {
            kind: "checkout",
            title: KIND_TITLE.checkout,
            text: _t("Elegí 2 por %(price)s: %(items)s. Se pueden combinar.", {
                price: this.cristalVgFormat(vg.checkout.price),
                items: (vg.checkout.items || []).join(", "),
            }),
            productId: promo.id,
            matched: [],
            orderUuid: order.uuid,
            amount: vg.checkout.price,
        };
        this.cristalVgLog(order, { product_id: promo.id, kind: "checkout" });
        return true;
    },

    async pay() {
        const order = this.get_order();
        if (order && !order.is_empty() && this.cristalVgActive(order)) {
            // No frena el cobro: la tarjeta aparece en la pantalla de pago.
            if (!this.cristalVgShowCheckout(order)) {
                this.cristalVg.card = null;
            }
        }
        return await super.pay(...arguments);
    },
});

export class VentaGuiadaCard extends Component {
    static template = "cristal_venta_guiada.Card";
    static props = {};

    setup() {
        this.pos = usePos();
    }

    get card() {
        const card = this.pos.cristalVg?.card;
        return card && card.orderUuid === this.pos.get_order()?.uuid ? card : null;
    }

    async accept() {
        await this.pos.cristalVgAccept();
    }

    dismiss() {
        this.pos.cristalVgDismiss();
    }
}

patch(ProductScreen, {
    components: { ...ProductScreen.components, VentaGuiadaCard },
});

patch(PaymentScreen, {
    components: { ...PaymentScreen.components, VentaGuiadaCard },
});
