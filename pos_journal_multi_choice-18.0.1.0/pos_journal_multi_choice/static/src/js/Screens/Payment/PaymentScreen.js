/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { onMounted } from "@odoo/owl";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => {
            if (this.is_check_default_journal()) {
                this.apply_default_journal();
            }
        });
    },

    is_check_default_journal() {
        var journal_id = this.pos.config.default_journal_id;
        if (journal_id) {
            return true
        }
    },
    apply_default_journal() {
        var journal_id = this.pos.config.default_journal_id;
        if (journal_id) {
            this.currentOrder.set_invoice_journal_id(journal_id.id);
            this.currentOrder.set_to_invoice(true);
        }
    },
    // Función para manejar el clic de selección de diarios
    click_diarios(journal_id) {
        const order = this.currentOrder;
        order.set_to_invoice(true);  // Para asegurarse de que el pedido esté configurado para facturar
        this.render();

        // Actualizar la selección del diario
        if (order.get_invoice_journal_id() !== journal_id) {
            order.set_invoice_journal_id(journal_id);
        } else {
            order.set_invoice_journal_id(false);
            order.set_to_invoice(false);
        }
    },

});
