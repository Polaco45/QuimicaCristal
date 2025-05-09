odoo.define('pos_fiscal_position_extension.journal_selector', function (require) {
    "use strict";

    const { PosGlobalState } = require('point_of_sale.models');
    const OrderWidget = require('point_of_sale.OrderWidget');
    const Registries = require('point_of_sale.Registries');
    const patch = require('web.patch');

    // Cargar campos necesarios de account.journal
    PosGlobalState.prototype.load_new_journals = async function () {
        const journals = await this.rpc({
            model: 'account.journal',
            method: 'search_read',
            args: [[['type', '=', 'sale'], ['pos_posted', '=', true]]],
            fields: ['id', 'name'],
        });
        this.pos_journals = journals;
    };

    patch(PosGlobalState.prototype, {
        async _processData(loadedData) {
            await this.load_new_journals();
            return this._super(...arguments);
        }
    });

    patch(OrderWidget.prototype, {
        setup() {
            this._super();
            this.journalOptionsVisible = false;
        },
        toggleJournalSelector() {
            this.journalOptionsVisible = !this.journalOptionsVisible;
            this.render();
        },
        selectJournal(event) {
            const journalId = parseInt(event.currentTarget.dataset.journalId);
            const journal = this.env.pos.pos_journals.find(j => j.id === journalId);
            if (journal) {
                this.env.pos.get_order().selected_journal_id = journal.id;
                this.journalOptionsVisible = false;
                this.render();
            }
        }
    });

    Registries.Component.extend(OrderWidget, {
        template: 'OrderWidgetWithJournalSelector',
    });
});
