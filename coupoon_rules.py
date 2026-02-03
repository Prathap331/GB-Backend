# coupoon_rules.py
# for DD specific coupons


COUPON_RULES = {
    # -------------------------
    # UNIVERSAL (QDIO)
    # -------------------------
    "QDIO": {
        "discount_type": "percentage",
        "discount_value": 10,
        "min_quantity": 1,
        "valid_days": 30,
    },

    # -------------------------
    # BRAND SPECIFIC
    # -------------------------
    "GB": {
        "discount_type": "percentage",
        "discount_value": 10,
        "min_quantity": 1,
        "valid_days": 30,
    },

    # You can add more anytime
    # "TBH": {...}
}
