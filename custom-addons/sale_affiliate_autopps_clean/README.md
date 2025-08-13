
# Affiliate PPS on Confirm (Clean)

- Adds `x_affiliate_key` to `sale.order`.
- Frontend JS picks `aff_key` / `aff` / `affiliate` from URL, stores cookie for 30 days,
  and persists the key on the active cart via JSON route.
- Does **not** override checkout routes. No `super().confirm_order` calls.
