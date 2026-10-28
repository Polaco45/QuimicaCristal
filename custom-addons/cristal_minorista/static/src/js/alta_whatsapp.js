/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { usePos } from "@point_of_sale/app/store/pos_hook";

// Alta por WhatsApp en la caja: al cobrar, si el cliente todavía no aceptó avisos,
// Guillermo le pregunta el celular. No cambia a nombre de quién se factura el ticket:
// sólo lo asocia al cliente real (cristal_customer_pid) para su historia de compras.

export class AltaWhatsapp extends Component {
    static template = "cristal_minorista.AltaWhatsapp";
    static props = {};

    setup() {
        this.pos = usePos();
        this.state = useState({ phone: "", name: "", error: "", busy: false });
    }

    get order() {
        return this.pos.get_order();
    }

    get anonymousId() {
        return this.pos.session?._cristal_min?.anonymous_partner_id || false;
    }

    get realPartner() {
        const partner = this.order?.get_partner();
        return partner && partner.id !== this.anonymousId ? partner : null;
    }

    get visible() {
        const order = this.order;
        if (!order || order.is_empty() || order.uiState.cristalAlta) {
            return false;
        }
        const partner = this.realPartner;
        return !partner || (!partner.cristal_mkt_optin && !partner.cristal_mkt_optout);
    }

    get phonePlaceholder() {
        return this.realPartner?.mobile || this.realPartner?.phone || _t("Celular, ej. 358 4123456");
    }

    async accept() {
        const phone = this.state.phone || this.realPartner?.mobile || this.realPartner?.phone || "";
        if (!phone.trim()) {
            this.state.error = _t("Falta el celular.");
            return;
        }
        this.state.busy = true;
        try {
            const res = await this.pos.data.call("res.partner", "cristal_pos_identify", [
                phone,
                this.state.name,
                this.realPartner?.id || false,
            ]);
            if (res.error) {
                this.state.error = res.error;
                return;
            }
            this.order.cristal_customer_pid = res.id;
            if (this.realPartner) {
                this.realPartner.cristal_mkt_optin = true;
            }
            this.order.uiState.cristalAlta = { done: true, name: res.name };
        } catch (error) {
            this.state.error = _t("No se pudo guardar (¿sin conexión?). Seguí cobrando.");
            console.warn("Alta WhatsApp:", error);
        } finally {
            this.state.busy = false;
        }
    }

    skip() {
        this.order.uiState.cristalAlta = { done: false };
    }
}

patch(PaymentScreen, {
    components: { ...PaymentScreen.components, AltaWhatsapp },
});
