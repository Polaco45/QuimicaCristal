/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ask } from "@point_of_sale/app/store/make_awaitable_dialog";

function idOf(value) {
    return (typeof value === "object" ? value?.id : value) || false;
}

// Diario que corresponde a la posición fiscal de la orden (la del cliente, la
// por defecto de la caja o la que eligió el vendedor para esta venta). El
// servidor aplica la misma regla al facturar.
function fiscalJournalId(order) {
    return idOf(order.fiscal_position_id?.cristal_sale_journal_id);
}

patch(PosOrder.prototype, {
    get_invoice_journal_id() {
        return fiscalJournalId(this) || super.get_invoice_journal_id(...arguments);
    },

    // Cliente nuevo en la venta: vuelve a valer la posición fiscal de su ficha.
    updatePricelistAndFiscalPosition() {
        super.updatePricelistAndFiscalPosition(...arguments);
        if (this.cristal_journal_manual) {
            this.update({ cristal_journal_manual: false });
        }
    },
});

patch(PaymentScreen.prototype, {
    // El vendedor puede cambiar el diario de ESTA venta, con confirmación. Lo
    // que se cambia es la posición fiscal de la venta (impuestos y diario van
    // juntos); la ficha del cliente no se toca.
    async click_diarios(journal_id) {
        const order = this.currentOrder;
        const currentId = order.get_invoice_journal_id();
        if (currentId === journal_id) {
            return;
        }
        const position = this.pos.models["account.fiscal.position"].find(
            (fp) => idOf(fp.cristal_sale_journal_id) === journal_id
        );
        if (!position) {
            if (!fiscalJournalId(order)) {
                return super.click_diarios(...arguments);
            }
            this.notification.add(
                _t("Ese diario no tiene una posición fiscal asociada: no se puede usar en esta venta."),
                { type: "warning" }
            );
            return;
        }
        const partner = order.get_partner();
        if (position.cristal_requires_afip && !partner?.cristal_has_afip_responsibility) {
            this.notification.add(
                _t(
                    "Para facturar con %s el cliente tiene que tener cargados el CUIT/DNI y la responsabilidad AFIP en su ficha.",
                    position.name
                ),
                { type: "danger" }
            );
            return;
        }
        const journalName = (id) =>
            this.pos.config.invoice_journal_ids.find((journal) => journal.id === id)?.name || "";
        const confirmed = await ask(this.dialog, {
            title: _t("¿Cambiar el diario de esta venta?"),
            body: _t(
                "¿Estás seguro que querés cambiar el diario de %(from)s a %(to)s (%(position)s)? Cliente: %(partner)s. El cambio vale solo para esta venta.",
                {
                    from: journalName(currentId) || _t("sin diario"),
                    to: journalName(journal_id),
                    position: position.name,
                    partner: partner?.name || _t("sin cliente"),
                }
            ),
            confirmLabel: _t("Sí, cambiar"),
            cancelLabel: _t("No"),
        });
        if (!confirmed) {
            return;
        }
        const totalBefore = order.get_total_with_tax();
        order.update({ fiscal_position_id: position, cristal_journal_manual: true });
        order.set_invoice_journal_id(journal_id);
        const totalAfter = order.get_total_with_tax();
        if (Math.abs(totalAfter - totalBefore) > 0.005) {
            this.notification.add(
                _t(
                    "Con el nuevo diario el total pasó de %(before)s a %(after)s. Revisá los pagos cargados.",
                    {
                        before: this.env.utils.formatCurrency(totalBefore),
                        after: this.env.utils.formatCurrency(totalAfter),
                    }
                ),
                { type: "warning", sticky: true }
            );
        }
    },
});
