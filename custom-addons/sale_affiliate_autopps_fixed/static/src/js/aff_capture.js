(function() {
    function getParam(name) {
        try {
            var url = new URL(window.location.href);
            return url.searchParams.get(name);
        } catch(e) { return null; }
    }
    function setCookie(name, value, days) {
        try {
            var d = new Date();
            d.setTime(d.getTime() + (days*24*60*60*1000));
            document.cookie = name + "=" + encodeURIComponent(value) + ";expires=" + d.toUTCString() + ";path=/";
        } catch(e) {}
    }
    function getCookie(name) {
        try {
            var match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
            return match ? decodeURIComponent(match[2]) : null;
        } catch(e) { return null; }
    }
    function postJSON(url, payload) {
        try {
            return fetch(url, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(payload || {}),
                credentials: "same-origin"
            });
        } catch(e) { return Promise.resolve(); }
    }

    document.addEventListener("DOMContentLoaded", function () {
        var key = getParam("aff_key") || getParam("affiliate_key") || getCookie("aff_key");
        if (!key) return;

        // Persistimos cookie 30 días
        try { setCookie("aff_key", key, 30); } catch(e){}

        // Notificamos al servidor para guardar en sesión / orden actual
        postJSON("/sale_affiliate_autopps/capture", {aff_key: key});
    });
})();