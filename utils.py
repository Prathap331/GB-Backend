
import io
from datetime import datetime, date, timezone
import random

# PDF Generator
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from services import supabase
from bs4 import BeautifulSoup
import csv
import textwrap



def calculate_order_pricing(order, validated_items, skip_brand_offers=False):
    """
    Brand-wise pricing with DB-driven tier offers.
    Used by both price-preview and order creation.
    """

    # 1️⃣ group items by brand
    brand_map = {}

    for item in validated_items:
        brand_id = item["brand_id"]

        if brand_id not in brand_map:
            brand_map[brand_id] = {
                "subtotal": 0.0,
                "quantity": 0,
                "discount": 0.0,
                "offer": None,
            }

        brand_map[brand_id]["subtotal"] += item["subtotal"]
        brand_map[brand_id]["quantity"] += item["quantity"]

    total_discount = 0.0
    now = datetime.now(timezone.utc).isoformat()


    # apply brand offers ONLY if no coupon
    if not skip_brand_offers:
        for brand_id, data in brand_map.items():
   
            offer_res = (
                supabase
                .table("brand_offer_active_view")
                .select("""
                    offer_id,
                    discount_type,
                    discount_value,
                    min_quantity
                """)
                .eq("brand_id", brand_id)
                .lte("min_quantity", data["quantity"])
                .execute()
            )

            if not offer_res.data:
                continue

            # pick best tier (highest discount)
            best_offer = max(
                offer_res.data,
                key=lambda o: o["discount_value"]
            )

            if best_offer["discount_type"] == "percentage":
                discount = round(
                    data["subtotal"] * (best_offer["discount_value"] / 100), 2
                )
            else:
                discount = round(best_offer["discount_value"], 2)

            data["discount"] = discount
            data["offer"] = best_offer
            total_discount += discount


    # 3️⃣ final totals
    subtotal = round(sum(i["subtotal"] for i in validated_items), 2)
    discounted = round(subtotal - total_discount, 2)

    gst_amount = round(discounted * 0.05, 2)
    final = round(discounted + gst_amount, 2)

    shipping = 49.0 if final < 499 else 0.0
    grand = round(final + shipping, 2)

    cod_fee = 0.0
    if order.payment_method == "COD":
        cod_fee = max(40.0, round(grand * 0.02, 2))
        grand = round(grand + cod_fee, 2)

    return {
        "subtotal": subtotal,
        "discount": round(total_discount, 2),
        "gst": gst_amount,
        "shipping_fee": shipping,
        "cod_fee": cod_fee,
        "total": grand,
        "brand_breakdown": brand_map,
    }


def generate_pdf_invoice(order_data, user_data, items_data):
    """
    Generates a PDF invoice in memory and returns the bytes.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # --- Header ---
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, height - 50, "Qdio")
    
    c.setFont("Helvetica", 12)
    c.drawRightString(width - 50, height - 50, "TAX INVOICE")

    c.setFont("Helvetica", 10)
    c.drawString(50, height - 70, "Flat no. 502, Meenakshi enclave MIG 891 KPHB phase 3")
    c.drawString(50, height - 85, "Kukatpally, Hyderabad, 500072")
    c.drawString(50, height - 100, "GSTIN: 36AAQCM4860P1ZK")
    c.drawString(50, height - 115, "Contact: support@qdio.shop")
    c.drawString(50, height - 130, "Registered Company: Morpho Technologies Pvt Ltd")

    c.line(50, height - 148, width - 50, height - 148)

    # --- Invoice Details ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, height - 170, f"Invoice #: INV-{order_data['order_id']}")
    
    try:
        dt = datetime.fromisoformat(order_data['created_at'].replace('Z', '+00:00'))
        date_str = dt.strftime("%d %b %Y")
    except:
        date_str = str(datetime.now().date())
        
    c.drawString(300, height - 170, f"Invoice Date: {date_str}")
    c.drawString(50, height - 185, f"Order ID: {order_data.get('razorpay_order_id') or 'N/A'}")

    # --- Bill To / Ship To ---
    y = height - 200
    c.drawString(50, y, "Bill To / Ship To:")
    c.setFont("Helvetica", 10)
    y -= 15
    c.drawString(50, y, user_data.get('full_name') or "Customer")
    y -= 15
    
    address_lines = user_data.get('address_line1', '').split('\n')
    for line in address_lines:
        c.drawString(50, y, line)
        y -= 12
    
    c.drawString(50, y, f"{user_data.get('city', '')}, {user_data.get('state', '')} - {user_data.get('postal_code', '')}")
    y -= 15
    c.drawString(50, y, f"Phone: {user_data.get('phone_number', '')}")

    # --- Items Table Header ---
    y = height - 300
    c.line(50, y, width - 50, y)
    y -= 15
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Item")
    c.drawString(300, y, "Rate")
    c.drawString(380, y, "Qty")
    c.drawString(450, y, "Total")
    y -= 10
    c.line(50, y, width - 50, y)

    # --- Items Rows ---
    c.setFont("Helvetica", 10)
    y -= 20
    
    for item in items_data:
        product = item.get("products") or {}

        name = (
            item.get("product_name")
            or product.get("product_name")
            or "Unknown Item"
        )

        category = (
            item.get("category")
            or product.get("category")
            or ""
        )

        display_name = f"{name} {category}".strip()

        price = item.get("price_per_unit") or item.get("price") or 0
        qty = item.get("quantity") or 1
        subtotal = item.get("subtotal") or (price * qty)


        c.drawString(50, y, display_name[:45]) 
        c.drawString(300, y, f"Rs. {price}")
        c.drawString(380, y, str(qty))
        c.drawString(450, y, f"Rs. {subtotal}")
        y -= 20

    c.line(50, y, width - 50, y)

    # --- Totals ---
    grand_total = float(order_data['total_amount'])
    tax_rate = 0.05
# Base amount (without GST)
    base_amount = grand_total / (1 + tax_rate)
# GST amount
    tax_amount = grand_total - base_amount
    # total_amount = grand_total
    y -= 10
    c.setFont("Helvetica", 10)
    
    c.drawRightString(width - 50, y, f"Subtotal: Rs. {base_amount:.2f}")
    y -= 15
    c.drawRightString(width - 50, y, f"CGST/SGST (5%): Rs. {tax_amount:.2f}")
    y -= 20 
    
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(width - 50, y, f"Grand Total: Rs. {grand_total:.2f}")
    
    # --- Notes Section ---
    y -= 40
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Notes:")
    
    c.setFont("Helvetica", 10)
    # y -= 15
    # contest_id = order_data.get('contest_id', 'Not Assigned')
    # c.drawString(50, y, f"Contest ID: {contest_id}")
    y -= 15
    
    # --- NEW: Lucky Number ---
    lucky_numbers = order_data.get('lucky_number', 'Not Assigned')
    if isinstance(lucky_numbers, list):
        for ln in lucky_numbers:
            c.drawString(50, y, f"Lucky Number: {ln}")
            y -= 15
    else:
        c.drawString(50, y, f"Lucky Number: {lucky_numbers}")
        y -= 15
    c.drawString(50, y, "Keep these numbers safe for future rewards!")

    # --- Terms and Conditions ---
    y -= 40
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Terms & Conditions:")
    
    c.setFont("Helvetica", 9)
    y -= 15
    c.drawString(50, y, "1. Your contest lucky number becomes invalid if you return the product.")
    y -= 12
    c.drawString(50, y, "2. All disputes are subject to Hyderabad jurisdiction only.")

    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(width / 2, 50, "Thank you for shopping with Qdio!")
    c.drawCentredString(width / 2, 35, "This is a computer generated invoice.")

    c.save()
    buffer.seek(0)
    return buffer.read()



#--- lucky number ---
def generate_unique_lucky_numbers(count: int):
    lucky_numbers = []

    existing_numbers = supabase.table("lucky_numbers") \
        .select("lucky_number") \
        .execute().data
    existing_set = {row["lucky_number"] for row in existing_numbers}

    while len(lucky_numbers) < count:
        ln = f"{random.randint(0, 9999999):07d}"
        if ln not in existing_set:
            lucky_numbers.append(ln)
            existing_set.add(ln)

    return lucky_numbers



# Convert custom supplier product JSON → our product format
def map_supplier_product(p: dict, supplier_id: str):
    return {
        "supplier_id": supplier_id,
        "supplier_product_id": p.get("id"),

        "product_name": p.get("title"),
        "description": p.get("description") or "",

        "price": p.get("price"),
        "mrp": p.get("mrp"),

        "stock_quantity": p.get("stock", 0),

        "is_active": True,
    }





# to avoid storing html descriptions
def clean_html(html):
    if not html:
        return None
    return BeautifulSoup(html, "html.parser").get_text().strip()


# shopify supplier product mapping
def map_shopify_product(p: dict, supplier_id: str):

    images = [
        img["src"]
        for img in p.get("images", [])
        if img.get("src")
    ]

    return {
        "supplier_id": supplier_id,
        "supplier_product_id": str(p["id"]),

        "product_name": p.get("title"),
        "description": clean_html(p.get("body_html")),
          # ✅ store full html-cleaned long description here
        "Product_description": clean_html(p.get("body_html")),

        # BRAND (very important)
        "brand_name": p.get("vendor"),

        
        "images": images,

        "is_active": True,
    }


def map_shopify_variant(v: dict, product_id: int):
    return {
        "product_id": product_id,
        "supplier_variant_id": str(v["id"]),
        "color": v.get("option1"),
        "size": v.get("option2"),
        "stock_quantity": v.get("inventory_quantity", 0),
        "is_active": True,
    }



# insert or update product based on supplier_product_id
def upsert_product(data: dict):

    # never send product_id (DB will manage it)
    data = {k: v for k, v in data.items() if k != "product_id"}

    res = (
        supabase.table("products")
        .upsert(data, on_conflict="supplier_id,supplier_product_id")
        .execute()
    )

    return res

def upsert_variant(data: dict):
    supabase.table("product_variants").upsert(
        data,
        on_conflict="supplier_variant_id"
    ).execute()



def fetch_product_metafields(shop: str, token: str, product_id: int):
    import requests

    url = f"https://{shop}/admin/api/2024-01/products/{product_id}/metafields.json"
    headers = {"X-Shopify-Access-Token": token}

    res = requests.get(url, headers=headers, timeout=10)
    
    if res.status_code != 200:
        return []
    print(f"[DEBUG] [Product metafields] {res.json()}")
    return res.json().get("metafields", [])



def dump_shopify_debug(products: list, shop: str, token: str):
    from datetime import datetime
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # 1️⃣ RAW JSON
    with open(f"shopify_debug_raw_{timestamp}.json", "w", encoding="utf-8") as f:
        import json
        json.dump(products, f, indent=2)

    # 2️⃣ DB-ALIGNED CSV
    with open(f"shopify_debug_summary_{timestamp}.csv", "w", newline="", encoding="utf-8") as f:
        import csv
        writer = csv.writer(f)

        writer.writerow([
            "supplier_product_id",
            "supplier_variant_id",

            "product_name",
            "description",
            "Product_description",

            "brand_name",
            "category",
            "segment",
            "sub_category",
            "category_group",

            "images",
            "tags",

            "Design",
            "Fit",
            "Neck",
            "Sleeve_type",
            "Wash_care",

            "size",
            "color",
            "stock_quantity",
            "price",
            "mrp",
        ])

        for p in products:

            # 🔹 OPTIONS MAP
            option_map = {
                opt.get("position"): opt.get("name", "").lower()
                for opt in p.get("options", [])
            }

            # 🔹 IMAGES
            images = [
                img.get("src")
                for img in p.get("images", [])
                if img.get("src")
            ]
            images_csv = ",".join(images)

            # 🔹 DESCRIPTIONS
            long_desc = p.get("body_html")
            short_desc = (
                long_desc[:200] if long_desc else None
            )

            # 🔹 TAGS
            tags = p.get("tags")  # comma-separated string

            # 🔹 METAFIELDS (optional)
            metafields = fetch_product_metafields(shop, token, p.get("id"))
            design = fit = neck = sleeve = wash_care = None

            for m in metafields:
                key = m.get("key", "").lower()
                val = m.get("value")
                if key == "design":
                    design = val
                elif key == "fit":
                    fit = val
                elif key in ("neck", "neck_type"):
                    neck = val
                elif key in ("sleeve", "sleeve_type"):
                    sleeve = val
                elif key in ("wash_care", "washcare"):
                    wash_care = val

            # 🔹 VARIANTS
            for v in p.get("variants", []):

                size = color = None
                for pos, opt_name in option_map.items():
                    value = v.get(f"option{pos}")
                    if not value:
                        continue
                    if "size" in opt_name:
                        size = value
                    elif "color" in opt_name:
                        color = value

                price = v.get("price")
                mrp = v.get("compare_at_price") or price
                stock = v.get("inventory_quantity", 0)

                writer.writerow([
                    str(p.get("id")),
                    str(v.get("id")),

                    p.get("title"),
                    short_desc,
                    long_desc,

                    p.get("vendor"),
                    p.get("product_type"),
                    None,          # segment
                    None,          # sub_category
                    None,          # category_group

                    images_csv,
                    tags,

                    design,
                    fit,
                    neck,
                    sleeve,
                    wash_care,

                    size,
                    color,
                    stock,
                    price,
                    mrp,
                ])

# for filling missing details - segment, sub-category, category-group, descriptions


# =========================================================
# TAG NORMALIZATION
# =========================================================
def normalize_tags(tags: str) -> set:
    """
    Converts:
      "Men, Oversized, Graphic"
    → {"men", "oversized", "graphic"}
    """
    if not tags:
        return set()
    return {t.strip().lower() for t in tags.split(",")}


# =========================================================
# RULE MAPS (EXTENDABLE)
# =========================================================

# Segment (who it is for)
SEGMENT_RULES = {
    "men": "Men",
    "mens": "Men",
    "male": "Men",
    "women": "Women",
    "womens": "Women",
    "female": "Women",
    "kids": "Kids",
    "boys": "Kids",
    "girls": "Kids",
}

# Sub-category (style / type)
# Order = priority (top wins)
SUB_CATEGORY_RULES = {
    "oversized": "Oversized",
    "graphic": "Graphic",
    "printed": "Graphic",
    "plain": "Plain",
    "solid": "Plain",
    "washed": "Washed",
    "cropped": "Cropped",
    "relaxed": "Relaxed Fit",
}

# Category group (topwear / bottomwear)
CATEGORY_GROUP_KEYWORDS = {
    "Topwear": ["t-shirt", "shirt", "top", "hoodie", "sweatshirt"],
    "Bottomwear": ["jeans", "pant", "trouser", "short"],
}


# =========================================================
# RULE DERIVATION FUNCTIONS
# =========================================================
def derive_segment(tags: set) -> str | None:
    for tag in tags:
        if tag in SEGMENT_RULES:
            return SEGMENT_RULES[tag]
    return None


def derive_sub_category(tags: set) -> str | None:
    """
    Returns the FIRST matching sub-category based on priority.
    """
    for tag, sub_cat in SUB_CATEGORY_RULES.items():
        if tag in tags:
            return sub_cat
    return None


def derive_category_group(category: str) -> str | None:
    """
    category = Shopify product_type
    """
    if not category:
        return None

    cat = category.lower()

    for group, keywords in CATEGORY_GROUP_KEYWORDS.items():
        if any(k in cat for k in keywords):
            return group

    return None


# =========================================================
# DESCRIPTION ENRICHMENT
# =========================================================
def derive_short_description(long_desc: str) -> str | None:
    if not long_desc:
        return None

    clean_text = clean_html(long_desc)

    return textwrap.shorten(
        clean_text,
        width=180,
        placeholder="..."
    )



def build_keywords(row: dict) -> set:
    keywords = set()

    def add_text(text):
        if not text:
            return
        for w in text.lower().replace("-", " ").split():
            keywords.add(w)

    # From tags
    add_text(row.get("tags"))

    # From product type
    add_text(row.get("category"))

    # From title
    add_text(row.get("product_name"))

    # From metafields (already resolved to text)
    add_text(row.get("Design"))
    add_text(row.get("Fit"))
    add_text(row.get("Neck"))
    add_text(row.get("Sleeve_type"))

    return keywords


# =========================================================
# MAIN ENRICHMENT FUNCTION
# =========================================================
def enrich_products_csv(input_csv: str, output_csv: str):
    """
    Reads RAW Shopify CSV →
    applies rule-based enrichment →
    writes CLEAN CSV for DB import.

    This function is meant to be RUN MANUALLY
    after CSV generation.
    """

    with open(input_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for row in rows:

        # -------------------------
        # TAGS
        # -------------------------
        keywords = build_keywords(row)

        # -------------------------
        # SEGMENT / CATEGORY
        # -------------------------
        row["segment"] = row.get("segment") or derive_segment(keywords)
        row["sub_category"] = row.get("sub_category") or derive_sub_category(keywords)
        row["category_group"] = row.get("category_group") or derive_category_group(
            row.get("category")
        )


        # -------------------------
        # DESCRIPTIONS
        # -------------------------
        # Short missing → derive from long
        if not row.get("description") and row.get("Product_description"):
            row["description"] = derive_short_description(
                row["Product_description"]
            )

        # Long missing → fallback to short
        if not row.get("Product_description") and row.get("description"):
            row["Product_description"] = row["description"]

        # NOTE:
        # If still None → UI should hide that section

    # -------------------------
    # WRITE CLEAN CSV
    # -------------------------
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)



if __name__ == "__main__":

    enrich_products_csv(
            input_csv="shopify_debug_summary_20260122_125516.csv",
            output_csv="shopify_products_cleaned.csv"
        )