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
    qty: "Llevando más, más barato",
};

function cleanName(product) {
    return (product?.display_name || "").replace(/^\[[^\]]*\]\s*/, "");
}

// Nombre sin código ni tamaño/variante: "Lavandina Doble Rend Crilimp (1 lt)" → "lavandina doble rend crilimp".
function baseName(product) {
    return cleanName(product).replace(/\s*\([^)]*\)\s*$/, "").trim().toLowerCase();
}

function isLoose(line) {
    return !line.combo_parent_id && !line.combo_line_ids?.length;
}

patch(PosStore.prototype, {
    async setup() {
        this.cristalVg = { card: null, queue: [] };
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
            // checkoutDone: la promo de caja ya se aceptó o se rechazó en este ticket.
            order.uiState.cristalVg = { shown: [], checkoutDone: false, checkoutLogged: false };
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

    // Escalera de mayor a menor para el producto recién cargado: primero el combo más
    // grande que lo incluye; si dice que no, el tamaño más grande; si no, el complemento.
    // La promo de caja (2 por $X) va al final, al cobrar, a todos.
    cristalVgAfterAdd(line) {
        const order = this.get_order();
        const product = line.product_id;
        this.cristalVg.card = null;
        this.cristalVg.queue = [];
        if (!this.cristalVgActive(order) || !product || product.isCombo()) {
            return;
        }
        const steps = [];
        const combo = this.cristalVgComboStep(order, product);
        if (combo) {
            steps.push(combo);
        }
        const state = this.cristalVgState(order);
        // "Llevando N": precio por cantidad de la lista (ej. 3 trapos de piso).
        const tier = this.cristalVgConfig().qty_tiers?.[product.id];
        const qtyKey = `qty-${product.id}`;
        if (tier && line.get_quantity() < tier[0] && !state.shown.includes(qtyKey)) {
            const [minQty, unit] = tier;
            const regular = product.get_price(order.pricelist_id, 1);
            if (unit < regular) {
                steps.push({
                    kind: "qty",
                    key: qtyKey,
                    title: KIND_TITLE.qty,
                    text: _t("Llevando %(n)s te sale %(unit)s cada uno (en vez de %(regular)s). Ahorra %(saving)s.", {
                        n: minQty,
                        unit: this.cristalVgFormat(unit),
                        regular: this.cristalVgFormat(regular),
                        saving: this.cristalVgFormat((regular - unit) * minQty),
                    }),
                    triggerId: product.id,
                    productId: product.id,
                    qty: minQty,
                    orderUuid: order.uuid,
                    amount: unit * minQty - regular * line.get_quantity(),
                });
            }
        }
        const inCart = new Set(order.lines.map((l) => l.product_id?.id));
        const suggestions = (this.cristalVgConfig().suggestions?.[product.id] || []).filter(
            ([pid]) => this.models["product.product"].get(pid) && !inCart.has(pid)
        );
        const size = suggestions.find(([, kind]) => kind === "size");
        const other = suggestions.find(([, kind]) => kind !== "size");
        for (const [pid, kind, text] of [size, other].filter(Boolean)) {
            const key = `${product.id}-${pid}`;
            if (state.shown.includes(key)) {
                continue;
            }
            steps.push({
                kind,
                key,
                title: KIND_TITLE[kind] || KIND_TITLE.manual,
                text,
                triggerId: product.id,
                productId: pid,
                orderUuid: order.uuid,
                amount: this.models["product.product"].get(pid).get_price(order.pricelist_id, 1),
            });
        }
        this.cristalVg.queue = steps;
        this.cristalVgNext(order);
    },

    // Muestra el próximo escalón pendiente (si el ticket sigue siendo el mismo).
    cristalVgNext(order) {
        const card = this.cristalVg.queue?.shift();
        if (!card || !order || card.orderUuid !== order.uuid) {
            this.cristalVg.card = null;
            return;
        }
        this.cristalVgState(order).shown.push(card.key);
        this.cristalVg.card = card;
        this.cristalVgLog(order, { trigger_product_id: card.triggerId, product_id: card.productId, kind: card.kind });
    },

    // El combo más grande (más caro) que incluye este producto y le conviene al cliente.
    cristalVgComboStep(order, product) {
        const vg = this.cristalVgConfig();
        const state = this.cristalVgState(order);
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
            if (combo.product_id === checkoutId || !this.models["product.product"].get(combo.product_id)) {
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
            const key = `combo-${combo.product_id}`;
            if (state.shown.includes(key)) {
                continue;
            }
            // Sin el producto exacto, sirve el mismo producto en otro tamaño (lavandina
            // de 1 lt → combo con la de 5 lts): al aceptar, el combo la reemplaza.
            let upgradePrice = 0;
            if (!matched.includes(product.id)) {
                const base = baseName(product);
                const idx = missing.findIndex((slot) =>
                    slot.some((id) => baseName(this.models["product.product"].get(id)) === base)
                );
                if (idx < 0) {
                    continue;
                }
                upgradePrice = slotPrice(missing[idx]);
                missing.splice(idx, 1);
                matched.push(product.id);
            }
            const loosePrice =
                upgradePrice +
                matched.filter((pid, i) => !(upgradePrice && i === matched.length - 1))
                    .reduce((sum, pid) => sum + priceOf(pid), 0) +
                missing.reduce((sum, slot) => sum + slotPrice(slot), 0);
            if (loosePrice <= combo.price) {
                continue;
            }
            if (!best || combo.price > best.combo.price) {
                best = { combo, matched, missing, key, saving: loosePrice - combo.price, loosePrice, upgrade: !!upgradePrice };
            }
        }
        if (!best) {
            return null;
        }
        const { combo, matched, missing, key, saving, loosePrice, upgrade } = best;
        let text;
        if (!missing.length) {
            text = _t("Ya lleva todo el %(name)s. Cobralo como combo: suelto %(loose)s, combo %(price)s. Ahorra %(saving)s.", {
                name: combo.name,
                loose: this.cristalVgFormat(loosePrice),
                price: this.cristalVgFormat(combo.price),
                saving: this.cristalVgFormat(saving),
            });
        } else {
            const names = missing
                .slice(0, 3)
                .map((slot) => cleanName(this.models["product.product"].get(slot[0])))
                .filter(Boolean);
            const more = missing.length > 3 ? _t(" y %s más", missing.length - 3) : "";
            text = _t("Ofrecé el %(name)s a %(price)s: suma %(missing)s%(more)s (suelto %(loose)s). Ahorra %(saving)s.", {
                name: combo.name,
                price: this.cristalVgFormat(combo.price),
                missing: names.join(", "),
                more,
                loose: this.cristalVgFormat(loosePrice),
                saving: this.cristalVgFormat(saving),
            });
        }
        if (upgrade) {
            text = _t("%(text)s Su %(product)s pasa a la del combo.", { text, product: cleanName(product) });
        }
        return {
            kind: "combo",
            key,
            title: KIND_TITLE.combo,
            text,
            triggerId: product.id,
            productId: combo.product_id,
            matched,
            orderUuid: order.uuid,
            amount: combo.price,
        };
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
            if (card.kind === "checkout") {
                this.cristalVgState(order).checkoutDone = true;
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
        if (card.kind === "qty") {
            // "Llevando N": se sube la cantidad de esa línea; la lista de precios baja el precio.
            const qtyLine = order.lines.find((x) => x.product_id?.id === card.productId && isLoose(x));
            if (qtyLine) {
                qtyLine.set_quantity(card.qty);
            }
            return;
        }
        if (card.kind === "size") {
            // Agrandar: el tamaño grande reemplaza a uno del chico, no se suma.
            const small = order.lines.find((x) => x.product_id?.id === card.triggerId && isLoose(x));
            if (small && small.get_quantity() > 1) {
                small.set_quantity(small.get_quantity() - 1);
            } else if (small) {
                order.removeOrderline(small);
            }
        }
        // La sugerencia ya es una variante concreta: se agrega sin pedir presentación/aroma.
        // Lo agregado también es un producto cargado: puede traer su propia sugerencia.
        const line = await this.addLineToCurrentOrder({ product_id: product }, {}, false);
        if (line) {
            this.cristalVgAfterAdd(line);
        }
    },

    cristalVgDismiss() {
        const card = this.cristalVg.card;
        const order = this.get_order();
        this.cristalVg.card = null;
        if (!card || !order) {
            return;
        }
        if (card.kind === "checkout") {
            this.cristalVgState(order).checkoutDone = true;
            return;
        }
        // Dijo que no: baja un escalón (combo → tamaño → complemento).
        this.cristalVgNext(order);
    },

    // Promo de caja (2 por $X): al final, en la pantalla de cobro, a todos los tickets.
    // Una sola vez por ticket.
    cristalVgShowCheckout(order) {
        const vg = this.cristalVgConfig();
        const promo = vg?.checkout && this.models["product.product"].get(vg.checkout.product_id);
        const state = this.cristalVgState(order);
        if (!promo || state.checkoutDone || order.lines.some((l) => l.product_id?.id === promo.id)) {
            return false;
        }
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
        if (!state.checkoutLogged) {
            state.checkoutLogged = true;
            this.cristalVgLog(order, { product_id: promo.id, kind: "checkout" });
        }
        return true;
    },

    async pay() {
        const order = this.get_order();
        if (order && !order.is_empty() && this.cristalVgConfig()) {
            // No frena el cobro: la tarjeta aparece en la pantalla de pago.
            this.cristalVg.queue = [];
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
