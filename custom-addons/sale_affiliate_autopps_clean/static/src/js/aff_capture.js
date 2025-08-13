
/** Copyright (LGPL-3)
 * Capture affiliate key from URL/cookie and persist it on the current cart.
 */
odoo.define('sale_affiliate_autopps_clean.aff_capture', function (require) {
    'use strict';
    var ajax = require('web.ajax');

    function getParamByNames(names) {
        var urlParams = new URLSearchParams(window.location.search || '');
        for (var i = 0; i < names.length; i++) {
            var v = urlParams.get(names[i]);
            if (v) return v;
        }
        return null;
    }

    function setCookie(name, value, days) {
        try {
            var d = new Date();
            d.setTime(d.getTime() + (days * 24 * 60 * 60 * 1000));
            document.cookie = name + '=' + encodeURIComponent(value) + ';path=/;expires=' + d.toUTCString();
        } catch (e) {}
    }

    function getCookie(name) {
        var value = ('; ' + document.cookie).split('; ' + name + '=');
        if (value.length === 2) return decodeURIComponent(value.pop().split(';').shift());
        return null;
    }

    function onShopPages() {
        var path = window.location.pathname || '';
        return path.indexOf('/shop') === 0;
    }

    function capture() {
        var key = getParamByNames(['aff_key', 'aff', 'affiliate']) || getCookie('x_affiliate_key');
        if (!key) return;

        // refresh cookie (30 days)
        setCookie('x_affiliate_key', key, 30);

        if (onShopPages()) {
            ajax.jsonRpc('/sale_affiliate_autopps/capture', 'call', { key: key }).then(function () {
                // ok
            }).catch(function () {
                // silent
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', capture);
    } else {
        capture();
    }
});
