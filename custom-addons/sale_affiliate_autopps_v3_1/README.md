# Affiliate PPS on Confirm (Auto) — v18.0.1.0.3

- Quita override de `/shop/payment` (en Odoo 18 esa ruta no la maneja `WebsiteSaleBase` y rompía el super).
- Agrega override de `/shop/confirm_order`.
- Resto igual: captura `aff_key` y genera PPS en `action_confirm` con logs.
