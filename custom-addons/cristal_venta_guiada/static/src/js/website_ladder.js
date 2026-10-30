/** @odoo-module **/

import { rpc } from "@web/core/network/rpc";
import { WebsiteSale } from "@website_sale/js/website_sale";

// Escalera de venta en la tienda: al agregar al carrito, un popup propio ofrece un paso por
// vez (combo → llevando N → tamaño grande → complemento). Reemplaza al configurador de
// productos opcionales de Odoo. Los combos siguen con su configurador nativo (eligen aroma).

function money(value) {
    return "$" + Math.round(value).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

class LadderPopup {
    constructor(steps, triggerId) {
        this.steps = steps;
        this.triggerId = triggerId;
        this.index = 0;
        this.added = 0;
        this.root = document.createElement("div");
        this.root.className = "cristal-ladder";
        document.body.appendChild(this.root);
        this.render();
    }

    get step() {
        return this.steps[this.index];
    }

    render() {
        const s = this.step;
        if (!s) {
            this.renderEnd();
            return;
        }
        this.root.innerHTML = `
            <div class="cristal-ladder__box">
                <div class="cristal-ladder__added">✓ Agregado al carrito</div>
                <div class="cristal-ladder__kind">${s.title}</div>
                <div class="cristal-ladder__body">
                    <img src="${s.product.image}" alt="" loading="lazy"/>
                    <div>
                        <div class="cristal-ladder__name">${s.product.name}</div>
                        <div class="cristal-ladder__text">${s.text}</div>
                    </div>
                </div>
                <div class="cristal-ladder__actions">
                    <button type="button" class="btn btn-primary btn-lg" data-act="yes">${s.cta}</button>
                    <button type="button" class="btn btn-link" data-act="no">No, gracias</button>
                </div>
                <div class="cristal-ladder__step">${this.index + 1} / ${this.steps.length}</div>
            </div>`;
        this.bind();
    }

    renderEnd() {
        this.root.innerHTML = `
            <div class="cristal-ladder__box">
                <div class="cristal-ladder__added">✓ ${this.added ? "Listo, lo sumamos al carrito" : "Agregado al carrito"}</div>
                <div class="cristal-ladder__actions">
                    <a class="btn btn-primary btn-lg" href="/shop/cart">Ir al carrito</a>
                    <button type="button" class="btn btn-link" data-act="close">Seguir comprando</button>
                </div>
            </div>`;
        this.bind();
    }

    bind() {
        this.root.querySelectorAll("[data-act]").forEach((el) => {
            el.addEventListener("click", (ev) => this.onAction(ev.currentTarget.dataset.act));
        });
        this.root.addEventListener("click", (ev) => {
            if (ev.target === this.root) {
                this.close();
            }
        });
    }

    async onAction(act) {
        if (act === "close") {
            return this.close();
        }
        if (act === "yes") {
            const s = this.step;
            if (s.kind === "combo") {
                window.location.href = s.product.url;
                return;
            }
            const btn = this.root.querySelector('[data-act="yes"]');
            btn.disabled = true;
            btn.textContent = "Agregando…";
            try {
                const data = await rpc("/cristal/vg/accept", { step: { ...s, trigger_id: this.triggerId } });
                this.added++;
                const badge = document.querySelector(".my_cart_quantity");
                if (badge && data.cart_quantity !== undefined) {
                    badge.textContent = data.cart_quantity;
                    badge.classList.remove("d-none");
                }
            } catch (error) {
                console.warn("Escalera web:", error);
            }
            // Una vez cambiado el tamaño, no tiene sentido ofrecer "llevando 3" del chico.
            if (s.kind === "size") {
                this.steps = this.steps.filter((x) => x.kind !== "qty");
                this.index = this.steps.indexOf(s);
            }
        }
        this.index++;
        this.render();
    }

    close() {
        this.root.remove();
    }
}

// Popup del carrito: "Completá tu compra". Barra de envío gratis, el combo que casi completa y
// los complementos de lo que lleva, con un clic para agregar. Se muestra una vez por estado del
// carrito (si agrega algo, vuelve a salir con sugerencias nuevas).
class CartPopup {
    constructor(data) {
        this.data = data;
        this.root = document.createElement("div");
        this.root.className = "cristal-ladder cristal-cart-popup";
        document.body.appendChild(this.root);
        this.render();
    }

    render() {
        const d = this.data;
        const pct = d.free_over ? Math.min(100, Math.round((d.subtotal / d.free_over) * 100)) : 100;
        const shipping = !d.free_over
            ? ""
            : d.missing > 0
            ? `<div class="cristal-cart-popup__ship">
                   <div>🚚 Te faltan <b>${money(d.missing)}</b> para el envío gratis a domicilio</div>
                   <div class="cristal-cart-popup__bar"><span style="width:${pct}%"></span></div>
               </div>`
            : `<div class="cristal-cart-popup__ship cristal-cart-popup__ship--ok">🚚 ¡Ya tenés envío gratis a domicilio!</div>`;
        const combo = d.combo
            ? `<a class="cristal-cart-popup__combo" href="${d.combo.url}">
                   <div><div class="cristal-ladder__kind">Ya tenés ${d.combo.matched} de ${d.combo.slots} del combo</div>
                   <b>${d.combo.name}</b> completo ${money(d.combo.price)} · ahorrás ${money(d.combo.saving)}</div>
                   <span class="btn btn-success">Ver el combo</span>
               </a>`
            : "";
        const cards = (d.products || [])
            .slice(0, 3)
            .map(
                (p) => `<div class="cristal-cart-popup__card" data-id="${p.id}">
                    <a href="${p.url}"><img src="${p.image}" alt="" loading="lazy"/></a>
                    <div class="cristal-cart-popup__name">${p.name}</div>
                    <div class="cristal-cart-popup__price">${money(p.price)}</div>
                    <button type="button" class="btn btn-outline-primary btn-sm" data-add="${p.id}">Agregar</button>
                </div>`
            )
            .join("");
        this.root.innerHTML = `
            <div class="cristal-ladder__box cristal-cart-popup__box">
                <button type="button" class="cristal-cart-popup__x" data-act="close" aria-label="Cerrar">×</button>
                <div class="cristal-ladder__kind">Antes de pagar</div>
                <div class="cristal-ladder__name">Completá tu compra</div>
                ${shipping}
                ${combo}
                ${cards ? `<div class="cristal-cart-popup__sub">Los que compran esto también llevan</div>
                           <div class="cristal-cart-popup__cards">${cards}</div>` : ""}
                <div class="cristal-ladder__actions">
                    <a class="btn btn-primary btn-lg" href="/shop/checkout">Ir a pagar</a>
                    <button type="button" class="btn btn-link" data-act="close">Seguir en el carrito</button>
                </div>
            </div>`;
        this.root.querySelectorAll("[data-act='close']").forEach((el) => el.addEventListener("click", () => this.close()));
        this.root.addEventListener("click", (ev) => {
            if (ev.target === this.root) {
                this.close();
            }
        });
        this.root.querySelectorAll("[data-add]").forEach((btn) =>
            btn.addEventListener("click", () => this.add(btn))
        );
    }

    async add(btn) {
        const p = (this.data.products || []).find((x) => String(x.id) === btn.dataset.add);
        btn.disabled = true;
        btn.textContent = "Agregando…";
        try {
            await rpc("/cristal/vg/accept", {
                step: { kind: "complement", product: p, trigger_id: p.trigger_id || false },
            });
            btn.textContent = "✓ Agregado";
            // El carrito se vuelve a dibujar con la línea nueva.
            window.location.reload();
        } catch (error) {
            console.warn("Popup carrito:", error);
            btn.disabled = false;
            btn.textContent = "Agregar";
        }
    }

    close() {
        this.root.remove();
    }
}

async function maybeCartPopup() {
    if (!/^\/shop\/cart\/?$/.test(window.location.pathname) || !document.querySelector("#cart_products")) {
        return;
    }
    let data;
    try {
        data = await rpc("/cristal/vg/cart", {});
    } catch (error) {
        return;
    }
    if (!data || !data.order_id || (!data.products?.length && !data.combo && !(data.free_over && data.missing > 0))) {
        return;
    }
    const key = `cristal_cart_popup_${data.order_id}_${data.cart_quantity}`;
    try {
        if (sessionStorage.getItem(key)) {
            return;
        }
        sessionStorage.setItem(key, "1");
    } catch (error) {
        // sin storage: se muestra igual
    }
    setTimeout(() => new CartPopup(data), 500);
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", maybeCartPopup);
} else {
    maybeCartPopup();
}

WebsiteSale.include({
    async _onProductReady(isOnProductPage = false) {
        if (this.isBuyNow) {
            return this._super(...arguments);
        }
        const productId = this.rootProduct.product_id;
        let ladder;
        try {
            ladder = await rpc("/cristal/vg/ladder", { product_id: productId, probe: true });
        } catch (error) {
            console.warn("Escalera web:", error);
            return this._super(...arguments);
        }
        if (ladder.native) {
            return this._super(...arguments);
        }
        // Agregar al carrito en la misma página (sin ir al carrito ni abrir el configurador).
        const stayOnPage = this.stayOnPageOption;
        this.stayOnPageOption = true;
        let data;
        try {
            data = await this._submitForm();
        } finally {
            this.stayOnPageOption = stayOnPage;
        }
        if (!data || data.warning) {
            return;
        }
        const result = await rpc("/cristal/vg/ladder", { product_id: productId, line_id: data.line_id });
        new LadderPopup(result.steps || [], productId);
    },
});
