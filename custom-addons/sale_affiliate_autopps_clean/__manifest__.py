{
    "name": "Affiliate PPS on Confirm (Clean)",
    "summary": "Capture affiliate key from URL/cookie and persist it on the active sale order without overriding checkout routes.",
    "version": "18.0.1.0.0",
    "license": "LGPL-3",
    "author": "ChatGPT",
    "depends": ["sale", "website_sale"],
    "data": [],
    "assets": {
        "web.assets_frontend": [
            "sale_affiliate_autopps_clean/static/src/js/aff_capture.js"
        ]
    },
    "installable": true,
    "application": false
}