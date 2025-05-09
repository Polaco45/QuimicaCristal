
odoo.define('pos_fiscal_auto_journal.payment_screen_extension', function(require){
    const PaymentScreen = require('point_of_sale.PaymentScreen');
    const Registries = require('point_of_sale.Registries');

    const ExtendedPaymentScreen = (PaymentScreen) => class extends PaymentScreen {
        setup() {
            super.setup();
            console.log("✅ PaymentScreen extendido para botón de diario");
        }
    };

    Registries.Component.extend(PaymentScreen, ExtendedPaymentScreen);
});
