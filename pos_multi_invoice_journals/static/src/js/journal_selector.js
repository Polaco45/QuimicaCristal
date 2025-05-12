/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment/payment_screen";
import { registry } from "@web/core/registry";

class JournalSelector extends PaymentScreen {
    // Al llegar al botón “Factura” mostramos un popup si hay >1 diario
    async _invoiceToCustomer() {
        const order = this.currentOrder;
        const allowed = this.env.pos.config.allowed_invoice_journal_ids || [];
        if (allowed.length > 1) {
            const { confirmed, payload } = await this.showPopup("SelectionPopup", {
                title: this.env._t("Seleccionar diario de factura"),
                list: allowed.map(j => ({ id: j.id, label: j.name })),
            });
            if (confirmed) {
                order.set_invoice_journal(payload.id);
            } else {
                return; // usuario canceló
            }
        }
        // sigue el flujo normal
        await super._invoiceToCustomer();
    }
}

registry.category("pos_screens").add("PaymentScreen", JournalSelector);
