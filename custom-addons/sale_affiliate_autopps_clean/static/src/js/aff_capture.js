/** @odoo-module **/

import { jsonRpc } from "@web/core/network/rpc_service";

/**
 * Capture affiliate key from URL (?aff_key= / ?aff= / ?affiliate=),
 * store it in a cookie (30 days), and persist it on the active sale order
 * (without touching checkout routes).
 */
(function () {
    function getParam(names) {
        const url = new URL(window.location.href);
        for (const n of names) {
            const v = url.searchParams.get(n);
            if (v) {
                return v.trim();
            }
        }
        return null;
    }

    function setCookie(name, value, days) {
        const d = new Date();
        d.setTime(d.getTime() + (days * 24 * 60 * 60 * 1000));
        const expires = "expires=" + d.toUTCString();
        document.cookie = name + "=" + encodeURIComponent(value) + ";" + expires + ";path=/;SameSite=Lax";
    }

    function getCookie(name) {
        const cname = name + "=";
        const parts = document.cookie.split(";");
        for (let c of parts) {
            while (c.charAt(0) === " ") c = c.substring(1);
            if (c.indexOf(cname) === 0) return decodeURIComponent(c.substring(cname.length, c.length));
        }
        return null;
    }

    async function persistIfPossible(key) {
        try {
            // Avoid creating empty SOs: only persist when we are in shop/cart/checkout pages
            const path = window.location.pathname || "";
            const inShopFlow = path.startsWith("/shop");
            if (!inShopFlow) return;

            const res = await jsonRpc("/sale_affiliate_autopps/persist", "call", { key });
            // Optional: can log to console for debugging, won't crash if service is unavailable
            if (res && res.ok) {
                console.debug("[sale_affiliate_autopps] persisted", res);
            }
        } catch (e) {
            console.debug("[sale_affiliate_autopps] persist skipped:", e);
        }
    }

    document.addEventListener("DOMContentLoaded", async () => {
        // 1) Get key from URL or cookie
        const urlKey = getParam(["aff_key", "aff", "affiliate"]);
        const cookieKey = getCookie("affiliate_key");
        const key = urlKey || cookieKey;

        // 2) If key from URL, refresh the cookie
        if (urlKey) {
            setCookie("affiliate_key", urlKey, 30);
        }

        // 3) Persist on SO if we have a key
        if (key) {
            await persistIfPossible(key);
        }
    });
})();