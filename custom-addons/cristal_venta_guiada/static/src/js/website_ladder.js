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
