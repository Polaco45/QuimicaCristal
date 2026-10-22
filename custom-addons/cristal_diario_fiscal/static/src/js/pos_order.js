/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

// Diario que corresponde a la posición fiscal de la orden (la del cliente o
// la por defecto de la caja). El servidor aplica la misma regla al facturar.
function fiscalJournalId(order) {
    const journal = order.fiscal_position_id?.cristal_sale_journal_id;
    return (typeof journal === "object" ? journal?.id : journal) || false;
}

patch(PosOrder.prototype, {
    get_invoice_journal_id() {
        return fiscalJournalId(this) || super.get_invoice_journal_id(...arguments);
    },
});

patch(PaymentScreen.prototype, {
    click_diarios(journal_id) {
        const fiscalId = fiscalJournalId(this.currentOrder);
        if (fiscalId && fiscalId !== journal_id) {
            this.notification.add(
                _t("El diario lo define la posición fiscal del cliente. Para cambiarlo, cambiá la posición fiscal en la ficha del cliente."),
                { type: "warning" }
            );
            return;
        }
        return super.click_diarios(...arguments);
    },
});
