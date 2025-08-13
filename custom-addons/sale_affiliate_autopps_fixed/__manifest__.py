# -*- coding: utf-8 -*-
{
    "name": "Affiliate PPS on Confirm (Fixed)",
    "summary": "Guarda aff_key en la orden desde URL/cookie y crea PPS al confirmar sin romper el checkout.",
    "version": "18.0.2.0",
    "license": "LGPL-3",
    "author": "ChatGPT",
    "website": "https://example.com",
    "category": "Website/Website",
    "depends": ["website_sale"],
    "data": [],
    "assets": {
        "web.assets_frontend": [
            "sale_affiliate_autopps_fixed/static/src/js/aff_capture.js",
        ],
    },
}