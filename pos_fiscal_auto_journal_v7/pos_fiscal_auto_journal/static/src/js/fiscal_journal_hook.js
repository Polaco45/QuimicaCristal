
odoo.define('pos_fiscal_auto_journal.fiscal_journal_hook', function(require){
    const { PosGlobalState } = require('point_of_sale.models');
    const Registries = require('point_of_sale.Registries');

    const PosFiscalJournalHook = (PosGlobalState) => class extends PosGlobalState {
        async _processData(loadedData) {
            await super._processData(...arguments);
            console.log("✅ Hook de diario fiscal cargado (v7)");
        }
    };

    Registries.Model.extend(PosGlobalState, PosFiscalJournalHook);
});
