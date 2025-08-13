
odoo.define('sale_affiliate_autopopps_clean.aff_capture', function (require) {
    'use strict';
    var publicRoot = require('web.public.root');
    var ajax = require('web.ajax');

    function getParam(name) {
        try {
            var url = new URL(window.location.href);
            return url.searchParams.get(name);
        } catch (e) {
            return null;
        }
    }

    function getCookie(name) {
        var value = '; ' + document.cookie;
        var parts = value.split('; ' + name + '=');
        if (parts.length === 2) return parts.pop().split(';').shift();
        return null;
    }

    function setCookie(name, value, days) {
        var d = new Date();
        d.setTime(d.getTime() + (days*24*60*60*1000));
        document.cookie = name + '=' + value + ';expires=' + d.toUTCString() + ';path=/;samesite=Lax';
    }

    publicRoot.ready.then(function () {
        var key = getParam('aff_key') || getCookie('aff_key');
        if (!key) { return; }
        setCookie('aff_key', key, 30);
        ajax.jsonRpc('/sale_affiliate_autopps/capture', 'call', {aff_key: key}).then(function () {
            // no-op
        });
    });
});
