/** @odoo-module **/
// Odoo desfija a diario los chats de WhatsApp vencidos y, por cada uno, muestra el aviso
// "Desfijó su conversación con X". Con cientos de chats por día es insoportable y no aporta
// nada: acá se descarta ese aviso antes de que aparezca. Los demás avisos siguen igual.
import { patch } from "@web/core/utils/patch";
import { notificationService } from "@web/core/notifications/notification_service";

const PATRONES = [
    /unpinned your conversation/i,
    /desfij[oó] (su|tu|la) conversaci[oó]n/i,
];

patch(notificationService, {
    start() {
        const service = super.start(...arguments);
        const addOriginal = service.add;
        service.add = (message, options) => {
            const texto = typeof message === "string" ? message : "";
            if (PATRONES.some((re) => re.test(texto))) {
                return () => {};
            }
            return addOriginal(message, options);
        };
        return service;
    },
});
