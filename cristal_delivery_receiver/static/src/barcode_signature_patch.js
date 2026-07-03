/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { SignatureDialog } from "@web/core/signature/signature_dialog";
import BarcodeModel from "@stock_barcode/models/barcode_model";
import BarcodePickingModel from "@stock_barcode/models/barcode_picking_model";

// En la app Código de barras, el diálogo "Agregar firma" oculta el campo de
// nombre (noInputName: true) y descarta el nombre ingresado. Este patch:
//   1) muestra el campo de nombre (aclaración de quién recibe), y
//   2) guarda ese nombre en stock.picking.receiver_name, que el remito imprime
//      debajo de la firma.
patch(BarcodePickingModel.prototype, {
    openSignatureDialog(validateAfterSignature = false) {
        const nameAndSignatureProps = {
            mode: "draw",
            displaySignatureRatio: 3,
            signatureType: "signature",
            noInputName: false, // mostrar el campo de aclaración (nombre de quien recibe)
        };
        const defaultName = ""; // arrancar vacío: que tipeen quién recibió
        const dialogProps = {
            defaultName,
            nameAndSignatureProps,
            uploadSignature: async (data) => {
                await this.uploadSignature(data);
                if (validateAfterSignature) {
                    await BarcodeModel.prototype._validate.call(this);
                }
            },
        };
        this.dialogService.add(SignatureDialog, dialogProps);
    },

    async uploadSignature({ signatureImage, name }) {
        const file = signatureImage.split(",")[1];
        this.ui.block();
        await this.orm.write(this.resModel, [this.resId], {
            signature: file,
            receiver_name: name || false,
        });
        this.ui.unblock();
        await this.save();
        this.trigger("refresh");
    },
});
