
odoo.define('pos_fiscal_auto_journal.journal_selector_button', function(require){
    const PaymentScreen = require('point_of_sale.PaymentScreen');
    const Registries = require('point_of_sale.Registries');

    const JournalSelectorButton = (PaymentScreen) => class extends PaymentScreen {
        mounted() {
            super.mounted();
            console.log("✅ Botón de selector de diario montado");
        }
    };

    Registries.Component.extend(PaymentScreen, JournalSelectorButton);
});
