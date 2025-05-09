odoo.define('pos_fiscal_position_extension.fiscal_position_hook', function (require) {
    "use strict";

    const models = require('point_of_sale.models');
    const _super_order = models.Order.prototype;

    models.load_fields('res.partner', ['fiscal_position_id']);

    models.Order = models.Order.extend({
        set_client: function (client) {
            _super_order.set_client.apply(this, arguments);
            if (client && client.fiscal_position_id) {
                this.fiscal_position_id = client.fiscal_position_id[0];
            }
        },
        export_as_JSON: function () {
            const json = _super_order.export_as_JSON.apply(this, arguments);
            json.fiscal_position_id = this.fiscal_position_id;
            return json;
        }
    });
});
