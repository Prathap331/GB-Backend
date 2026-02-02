# routers.py
from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from typing import List, Optional
from datetime import datetime, timedelta, timezone
import uuid
from fastapi import Header, HTTPException
import json
import razorpay

from supabase import create_client
from services import (
    SYNC_SECRET,
    fetch_supplier_products,
    supabase,
    razorpay_client,
    RAZORPAY_KEY_ID,
    get_current_user,
    supabase_anon
)
from schemas import (
    BrandResponse, CategoryResponse, CouponGenerateRequest, CouponGenerateResponse, CouponValidateRequest, CouponValidateResponse, DeliveryStatusCreate, DeliveryStatusEnum, PartnerCreate, PartnerResponse, Product, ProductUpdate, 
    Order, OrderCreate, OrderUpdate,
    Profile, ProfileBase,
    DeliveryPartner,
    PaymentVerificationRequest, RefreshTokenRequest,ReturnCreate, ReturnResponse, ReturnStatusEnum, ReturnUpdate, Supplier,
    UserCreate, UserForgotPassword, UserResetPassword, UserResponse,
    Token,
)

from utils import (
    calculate_order_pricing,
    generate_pdf_invoice,
    generate_unique_lucky_numbers,
    map_supplier_product,
    upsert_product,
)

from services import (
    SUPABASE_URL, SUPABASE_ANON_KEY,
)


router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@router.get("/")
def read_root():
    return {"message": "Welcome to the E-Commerce API v3 (Razorpay)"}


# AUTH ROUTERS

@router.post("/auth/signup", response_model=UserResponse)
async def signup(user: UserCreate):
    try:
        res = supabase.auth.sign_up({
            "email": user.email,
            "password": user.password,
            "options": {"data": {"full_name": user.full_name, "phone": user.phone_number}}
        })

        if res.user:
            profile_check = supabase.table("profiles").select("id").eq("id", res.user.id).execute()

            if  profile_check.data:
                raise HTTPException(status_code=409, detail="Account already exists. Please login instead.")

            return UserResponse(id=res.user.id, email=res.user.email, created_at=res.user.created_at)

        raise HTTPException(400, "Could not create user")

    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(400, str(e))


# login
@router.post("/auth/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    try:
        res = supabase.auth.sign_in_with_password({
            "email": form_data.username,
            "password": form_data.password
        })
        return Token(
            access_token=res.session.access_token,
            refresh_token=res.session.refresh_token,
            token_type="bearer"
        )
    except:
        raise HTTPException(400, "Incorrect email or password")


# -----------------------------
# 🔁 REFRESH ACCESS TOKEN ROUTE
# -----------------------------
@router.post("/auth/refresh", response_model=Token)
async def refresh_access_token(payload: RefreshTokenRequest):

    refresh_token = payload.refresh_token

    res = supabase.auth.refresh_session(refresh_token)

    return Token(
        access_token=res.session.access_token,
        refresh_token=res.session.refresh_token,
        token_type="bearer"
    )


@router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: UserResponse = Depends(get_current_user)):
    return current_user


@router.post("/auth/forgot-password")
async def forgot_password(data: UserForgotPassword):
    """
    Trigger a password reset email via Supabase.
    Handles rate limiting errors gracefully.
    """
    try:
        # UPDATE: Set the redirect URL explicitly.
        # Change this URL to your actual frontend reset page.
        # Example for local testing: "http://localhost:3000/reset-password"
        # Example for production: "https://goldenbanana.vercel.app/reset-password"  
        redirect_url = "https://www.qdio.shop/reset-password" 
        
        supabase.auth.reset_password_email(data.email, options={"redirectTo": redirect_url})
    

       

        return {"message": "Password reset email sent if account exists"}
        
    except Exception as e:
        error_msg = str(e)
        
        # Check for Rate Limit or Server errors from Supabase email service
        if "556" in error_msg or "429" in error_msg:
             raise HTTPException(
                 status_code=status.HTTP_429_TOO_MANY_REQUESTS, 
                 detail="Too many email requests. Please wait a few minutes before trying again."
             )
             
        # For security, we generally don't want to tell the user if the email failed 
        # (unless it's a rate limit), so we often return success or a generic error.
        # But for dev debugging, we return the detail.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Email service error: {error_msg}")



@router.post("/auth/reset-password")
async def reset_password(
    data: UserResetPassword,
    token: str = Depends(oauth2_scheme)
):
    try:
        user_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

        # Attach the token to this client session
        user_client.auth.set_session(
            access_token=token,
            refresh_token=""
        )

        user_client.auth.update_user({"password": data.new_password})
        return {"message": "Password updated successfully"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Profile Endpoints ---
@router.get("/profiles/me", response_model=Profile)
async def get_my_profile(current_user: UserResponse = Depends(get_current_user)):
    try:
        # 🔐 Create user-scoped Supabase client (RLS enforced)
        client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        client.postgrest.auth(current_user.token)

        # READ profile as logged-in user
        res = (
            client
            .table("profiles")
            .select("*")
            .eq("id", str(current_user.id))
            .maybe_single()
            .execute()
        )

        # --- AUTO CREATE PROFILE (Google / first login users) ---
        if not res or not res.data:
            profile = {
                "id": str(current_user.id),
                "full_name": current_user.email.split("@")[0],
                "email": current_user.email,
                "gender": None,
                "phone_number": None,
                "address_line1": None,
                "address_line2": None,
                "city": None,
                "state": None,
                "postal_code": None,
                "country": None,
                "city_preference": "",
                "voluntary_consent": False,
                "fee_consent": False,
                "account_status": "active",
                "updated_at": datetime.utcnow().isoformat(),
            }

            insert_res = client.table("profiles").insert(profile).execute()
            return insert_res.data[0]
        # -------------------------------------------------------

        return res.data

    except HTTPException:
        raise
    except Exception as e:
        if "JWT expired" in str(e):
            raise HTTPException(status_code=401, detail="JWT expired")

        raise HTTPException(status_code=500, detail=str(e))



@router.put("/profiles/me", response_model=Profile)
async def update_my_profile(
    profile: ProfileBase,
    current_user: UserResponse = Depends(get_current_user)
):
    try:
        client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        client.postgrest.auth(current_user.token)

        update_data = profile.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(400, "No update data provided")

        res = (
            client
            .table("profiles")
            .update(update_data)
            .eq("id", str(current_user.id))
            .execute()
        )

        if not res.data:
            raise HTTPException(404, "Profile update failed")

        return res.data[0]

    except HTTPException:
        raise
    except Exception as e:
        if "JWT expired" in str(e):
            raise HTTPException(status_code=401, detail="JWT expired")

        raise HTTPException(status_code=500, detail=str(e))


# --- Product Endpoints ---

@router.get("/products", response_model=List[Product])
async def get_products():
    try:
        res = supabase.table("products").select("*").order("created_at", desc=True).execute()
        products = res.data

        # Convert images from string to list safely
        for p in products:
            if isinstance(p.get("images"), str):
                try:
                    p["images"] = json.loads(p["images"])
                except:
                    p["images"] = []  # fallback

        return products

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: int):
    try:
        res = supabase.table("products").select("*").eq("product_id", product_id).single().execute()
        product = res.data
        if not product:
            raise HTTPException(404, "Product not found")

        # Convert images string → list
        if isinstance(product.get("images"), str):
            try:
                product["images"] = json.loads(product["images"])
            except:
                product["images"] = []

        return product

    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/products/base/{base_product_id}", response_model=List[Product])
async def get_products_by_base_id(base_product_id: int):
    try:
        res = (
            supabase.table("products")
            .select("*")
            .eq("base_product_id", base_product_id)
            .eq("is_active", True)
            .order("created_at", desc=True)
            .execute()
        )

        if not res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No variants found for this base product"
            )

        products = res.data
    
         # ✅ Convert images string → list
        for p in products:
            if isinstance(p.get("images"), str):
                try:
                    p["images"] = json.loads(p["images"])
                except:
                    p["images"] = []

        return products

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )



# --- Updated Product Update (Handles Arrays) ---
@router.put("/products/{product_id}", response_model=Product)
async def update_product(
    product_id: int, 
    product_update: ProductUpdate,
    current_user: UserResponse = Depends(get_current_user)
):
    try:
        update_data = product_update.model_dump(exclude_unset=True)
        if not update_data:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")

        update_data["updated_at"] = datetime.now().isoformat()
        res = supabase.table("products").update(update_data).eq("product_id", product_id).execute()
        if not res.data or len(res.data) == 0:
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found or update failed")
        return res.data[0]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))




# --- Delivery Partner Endpoints ---
@router.get("/delivery-partners", response_model=List[DeliveryPartner])
async def get_delivery_partners(current_user: UserResponse = Depends(get_current_user)):
    try:
        res = supabase.table("delivery_partners").select("*").execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/orders/price-preview")
async def price_preview(order: OrderCreate):

    validated_items = []

    # ---------------------------------
    # 1️⃣ Validate items
    # ---------------------------------
    for item in order.items:
        variant = (
            supabase.table("product_variants")
            .select("variant_id, product_id, stock_quantity")
            .eq("variant_id", item.variant_id)
            .single()
            .execute()
        ).data

        if variant["stock_quantity"] < item.quantity:
            raise HTTPException(400, "Insufficient stock")

        product = (
            supabase.table("products")
            .select("product_id, brand_id, price")
            .eq("product_id", variant["product_id"])
            .single()
            .execute()
        ).data

        subtotal = product["price"] * item.quantity

        validated_items.append({
            "variant_id": variant["variant_id"],
            "product_id": product["product_id"],
            "brand_id": product["brand_id"],
            "quantity": item.quantity,
            "price_per_unit": product["price"],
            "subtotal": subtotal,
        })


    has_coupon = bool(order.coupon_code)

    # ---------------------------------
    # 2️⃣ Apply BRAND offers
    # ---------------------------------
    pricing = calculate_order_pricing(order, validated_items, skip_brand_offers=has_coupon)

    coupon_discount = 0.0

    # ---------------------------------
    # 3️⃣ Apply COUPON (FIXED)
    # ---------------------------------
    if order.coupon_code:
        variant_ids = [i["variant_id"] for i in validated_items]

        # ✅ Validate coupon
        res = supabase.rpc(
            "validate_coupon_for_cart",
            {
                "p_coupon_code": order.coupon_code,
                "p_variant_ids": variant_ids,
            }
        ).execute()

        if not res.data or not res.data[0]["valid"]:
            raise HTTPException(400, res.data[0]["message"])

        coupon_row = res.data[0]

        # ✅ Fetch offer_id from coupons table
        coupon = (
            supabase.table("coupons")
            .select("offer_id")
            .eq("coupon_id", coupon_row["coupon_id"])
            .single()
            .execute()
        ).data

        # ✅ Fetch EXACTLY ONE offer
        offer = (
            supabase.table("offers")
            .select("discount_type, discount_value")
            .eq("offer_id", coupon["offer_id"])
            .single()
            .execute()
        ).data

        base_amount = pricing["subtotal"] - pricing["discount"]


        if offer["discount_type"] == "percentage":
            coupon_discount = round(
                base_amount * (offer["discount_value"] / 100), 2
            )
        else:
            coupon_discount = round(offer["discount_value"], 2)

        pricing["coupon_discount"] = coupon_discount
        pricing["brand_discount"] = 0.0
        pricing["total_discount"] = coupon_discount
        pricing["total"] = round(base_amount - coupon_discount, 2)

    return pricing


# --- Order Endpoints (UPDATED WITH RAZORPAY) ---
@router.post("/orders", response_model=Order)
async def create_order(
    order: OrderCreate,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Create a new order using variant_id (size-based).
    Validates stock from product_variants and stores variant_id in order_items.
    """

    # 1️⃣ Get user profile / address
    try:
        profile_res = (
            supabase.table("profiles")
            .select("*")
            .eq("id", str(current_user.id))
            .maybe_single()
            .execute()
        )

        profile = profile_res.data or {}
        if not profile:
            profile = {
                "id": str(current_user.id),
                "full_name": None,
                "phone_number": None,
                "address_line1": None,
                "address_line2": None,
                "city": None,
                "state": None,
                "postal_code": None,
                "country": None,
                "city_preference": "",
                "voluntary_consent": False,
                "fee_consent": False,
                "account_status": "active",
                "updated_at": datetime.utcnow().isoformat(),
            }
            supabase.table("profiles").insert(profile).execute()

        required_fields = [
            profile.get("full_name"),
            profile.get("address_line1"),
            profile.get("city"),
            profile.get("postal_code"),
        ]
        if any(f in (None, "", " ") for f in required_fields):
            raise HTTPException(
                400,
                "Please complete your profile (name, address, city, postal code) before ordering.",
            )

        delivery_address = (
            f"{profile.get('full_name','')}\n"
            f"{profile.get('address_line1','')}\n"
            f"{profile.get('address_line2','')}\n"
            f"{profile.get('city','')}, {profile.get('state','')} {profile.get('postal_code','')}\n"
            f"{profile.get('country','')}"
        )

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(500, f"Error fetching profile: {e}")


    # 2️⃣ VALIDATE VARIANTS, LOAD PRODUCTS & CALCULATE TOTAL
    try:
        if not order.items:
            raise HTTPException(400, "No items in order")

        validated_items = []
        total_amount = 0.0

        for item in order.items:
            variant_id = item.variant_id
            qty = item.quantity

            # 🛡 1️⃣ ensure variant belongs to product
            if variant_id:
                check = (
                    supabase.table("product_variants")
                    .select("variant_id, product_id")
                    .eq("variant_id", variant_id)
                    .maybe_single()
                    .execute()
                )

                if not check.data or check.data["product_id"] != item.product_id:
                    variant_id = None   # force fallback


            # 🔁 2️⃣ fallback: find variant from product + size (✅ color removed)
            if not variant_id or str(variant_id).lower() in ["", "none", "null"]:
                v = (
                    supabase.table("product_variants")
                    .select("variant_id, product_id, size, stock_quantity, price, mrp")
                    .eq("product_id", item.product_id)
                    .eq("size", item.size)
                    .maybe_single()
                    .execute()
                )

                if not v or not v.data:
                    raise HTTPException(
                        400,
                        f"No variant found for product {item.product_id} with size '{item.size}'"
                    )

                variant = v.data
                variant_id = variant["variant_id"]

            else:
                # already valid → fetch full row
                v = (
                    supabase.table("product_variants")
                    .select("variant_id, product_id, size, stock_quantity, price, mrp")
                    .eq("variant_id", variant_id)
                    .single()
                    .execute()
                )

                variant = v.data


            # 📦 stock validation
            if variant["stock_quantity"] < qty:
                raise HTTPException(
                    400,
                    f"Not enough stock for size {variant['size']}"
                )

            # 🎯 supplier details + product price
            p = (
                supabase.table("products")
                .select("product_id, brand_id, price, color, supplier_id, supplier_product_id")
                .eq("product_id", variant["product_id"])
                .single()
                .execute()
            )

            product = p.data

            # ensure product has brand (required for offers)
            if not product.get("brand_id"):
                raise HTTPException(
                    400,
                    f"Product {variant['product_id']} has no brand assigned"
                )

            price_raw = product.get("price")

            if price_raw is None:
                raise HTTPException(
                    400,
                    f"Product {variant['product_id']} has no price available"
                )

            price_per_unit = round(float(price_raw), 2)

            if price_per_unit <= 0:
                raise HTTPException(
                    400,
                    f"Variant {variant_id} has invalid price {price_per_unit}"
                )

            subtotal = price_per_unit * qty
            total_amount += subtotal

            validated_items.append(
                {
                    "variant_id": variant_id,
                    "product_id": variant["product_id"],
                    "brand_id": product["brand_id"],
                    "quantity": qty,
                    "price_per_unit": price_per_unit,
                    "subtotal": subtotal,
                    "new_stock": variant["stock_quantity"] - qty,
                    "supplier_id": product["supplier_id"],
                    "supplier_product_id": product["supplier_product_id"],
                    "size": variant.get("size"),
                    "color": product.get("color"),
                    
                }
            )
        

        has_coupon = bool(order.coupon_code)


        # 🔢 shared pricing (AFTER full loop)
        pricing = calculate_order_pricing(order, validated_items, skip_brand_offers=has_coupon)

        # ===============================
        # 🎟 APPLY COUPON (SINGLE SOURCE OF TRUTH)
        # ===============================
        coupon_data = None
        coupon_discount = 0.0

        if order.coupon_code:
            variant_ids = [item["variant_id"] for item in validated_items]

            # 1️⃣ Validate coupon
            res = supabase.rpc(
                "validate_coupon_for_cart",
                {
                    "p_coupon_code": order.coupon_code,
                    "p_variant_ids": variant_ids,
                }
            ).execute()

            if not res.data or not res.data[0]["valid"]:
                raise HTTPException(400, res.data[0]["message"])

            coupon_data = res.data[0]

            # 2️⃣ Get offer_id from coupon
            coupon_row = (
                supabase.table("coupons")
                .select("offer_id")
                .eq("coupon_id", coupon_data["coupon_id"])
                .single()
                .execute()
            ).data

            # 3️⃣ Fetch offer
            offer = (
                supabase.table("offers")
                .select("discount_type, discount_value")
                .eq("offer_id", coupon_row["offer_id"])
                .single()
                .execute()
            ).data

            # 4️⃣ Apply coupon on TOP of brand-discounted total
            base_amount = pricing["subtotal"] - pricing["discount"]


            if offer["discount_type"] == "percentage":
                coupon_discount = round(
                    base_amount * (offer["discount_value"] / 100), 2
                )
            else:
                coupon_discount = round(offer["discount_value"], 2)

            pricing["coupon_discount"] = coupon_discount
            pricing["total"] = round(base_amount - coupon_discount, 2)

        # ---------- FINAL TOTALS ----------
        grand_total = pricing["total"]
        gst_amount = pricing["gst"]
        shipping_fee = pricing["shipping_fee"]
        cod_fee = pricing["cod_fee"]


        # 🔎 Map brand → applied offer info (used later while inserting order_items)
        brand_offer_map = {}

        for brand_id, data in pricing.get("brand_breakdown", {}).items():
            if data.get("offer"):
                brand_offer_map[brand_id] = {
                    "offer_id": data["offer"]["offer_id"],
                    "discount_type": data["offer"]["discount_type"],
                    "total_discount": data["discount"],
                }

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(500, f"Error validating items: {e}")



    # 3️⃣ CREATE ORDER
    contest_id = uuid.uuid4().hex
    lucky_numbers = generate_unique_lucky_numbers(int(total_amount // 1000))

    try:
        order_data = {
            "user_id": str(current_user.id),
            "total_amount": round(grand_total, 2),
            "payment_method": order.payment_method,
            "delivery_address": delivery_address,
            "payment_status": "Pending",
            "order_status": "Pending",
            "contest_id": contest_id,
            "lucky_number": lucky_numbers,
            "opt_out_delivery": order.opt_out_delivery,
        }

        # ✅ STEP 5: Attach coupon ONLY from backend validation
        if coupon_data:
            order_data["coupon_id"] = coupon_data["coupon_id"]
            order_data["partner_id"] = coupon_data["partner_id"]


        order_res = supabase.table("orders").insert(order_data).execute()

        if not order_res.data:
            raise HTTPException(500, "Order insert returned no data")

        new_order = order_res.data[0]
        new_order_id = new_order["order_id"]

        for ln in lucky_numbers:
            supabase.table("lucky_numbers").insert(
                {
                    "order_id": new_order_id,
                    "user_id": str(current_user.id),
                    "lucky_number": ln,
                }
            ).execute()

    except Exception as e:
        raise HTTPException(500, f"Error creating order in DB: {e}")



    # 4️⃣ CREATE ORDER ITEMS (store VARIANT_ID)
    try:
        payload = []

        # count items per brand (used to split discount evenly)
        brand_item_count = {}
        for item in validated_items:
            brand_item_count[item["brand_id"]] = (
                brand_item_count.get(item["brand_id"], 0) + 1
            )

        for item in validated_items:
            applied_offer_id = None
            discount_amount = 0.0
            discount_type = None

            # check if this brand has an applied offer
            if item["brand_id"] in brand_offer_map:
                offer_info = brand_offer_map[item["brand_id"]]

                applied_offer_id = offer_info["offer_id"]
                discount_type = offer_info["discount_type"]

                # split brand discount equally across items
                discount_amount = round(
                    offer_info["total_discount"]
                    / brand_item_count[item["brand_id"]],
                    2
                )

            payload.append(
                {
                    "order_id": new_order_id,
                    "product_id": item["product_id"],
                    "variant_id": item["variant_id"],
                    "quantity": item["quantity"],
                    "price_per_unit": item["price_per_unit"],
                    "subtotal": item["subtotal"],

                    # offer persistence
                    "applied_offer_id": applied_offer_id,
                    "discount_amount": discount_amount,
                    "discount_type": discount_type,

                    "supplier_id": item["supplier_id"],
                    "supplier_product_id": item["supplier_product_id"],

                    "size": item["size"],
                    "color": item["color"],
                }
            )

        supabase.table("order_items").insert(payload).execute()

    except Exception as e:
        supabase.table("orders").delete().eq("order_id", new_order_id).execute()
        raise HTTPException(500, f"Error creating order items: {e}")



    # 5️⃣ RAZORPAY LOGIC (unchanged)
    razorpay_order_id = None
    if order.payment_method == "Online":
        try:
            rzp_order = razorpay_client.order.create(
                data={
                    "amount": int(round(order_data["total_amount"] * 100)),
                    "currency": "INR",
                    "receipt": f"order_rcptid_{new_order_id}",
                    "notes": {
                        "internal_order_id": new_order_id,
                        "user_id": str(current_user.id),
                        "contest_id": contest_id,
                        "lucky_number": lucky_numbers,
                        "opt_out_delivery": str(order.opt_out_delivery),
                    },
                }
            )

            razorpay_order_id = rzp_order["id"]

            supabase.table("orders").update(
                {"razorpay_order_id": razorpay_order_id}
            ).eq("order_id", new_order_id).execute()

        except Exception as e:
            supabase.table("orders").delete().eq("order_id", new_order_id).execute()
            raise HTTPException(500, f"Razorpay creation failed: {e}")



    # 6️⃣ DEDUCT STOCK PER VARIANT
    for item in validated_items:
        (
            supabase
            .table("product_variants")
            .update({"stock_quantity": item["new_stock"]})
            .eq("variant_id", item["variant_id"])
            .execute()
        )



    # 7️⃣ RETURN FINAL ORDER
    full_order = (
        supabase.table("orders")
        .select("*, order_items(*, products(product_name, category, sub_category, images))")
        .eq("order_id", new_order_id)
        .single()
        .execute()
    )

    final_order = Order.model_validate(full_order.data)

    if razorpay_order_id:
        final_order.razorpay_order_id = razorpay_order_id
        final_order.razorpay_key_id = RAZORPAY_KEY_ID

    final_order.shipping_fee = shipping_fee
    final_order.gst_amount = gst_amount
    final_order.cod_fee = cod_fee
    final_order.brand_discount = pricing.get("discount", 0)
    final_order.coupon_discount = pricing.get("coupon_discount", 0)
    final_order.total_discount = (
        final_order.brand_discount + final_order.coupon_discount
    )


    return final_order


@router.get("/orders/me", response_model=List[Order])
async def get_my_orders(current_user: UserResponse = Depends(get_current_user)):
    try:
        orders_res = (
            supabase
            .table("orders")
            .select(
                "*, order_items(*, products(product_name,category,sub_category,images))"
            )
            .eq("user_id", str(current_user.id))
            .order("created_at", desc=True)
            .execute()
        )

        returns_res = (
            supabase
            .table("returns")
            .select("order_id, product_id, status")
            .eq("user_id", str(current_user.id))
            .execute()
        )

        returns_map = {
            (r["order_id"], r["product_id"]): r["status"]
            for r in returns_res.data
        }

        now = datetime.now(timezone.utc)

        for o in orders_res.data:
            return_allowed = (
                o.get("delivery_date")
                and o.get("return_valid_till")
                and now <= datetime.fromisoformat(o["return_valid_till"])
            )

            o["return_allowed"] = return_allowed

            for item in o["order_items"]:
                key = (o["order_id"], item["product_id"])

                if key in returns_map:
                    item["return_status"] = returns_map[key]
                    item["return_eligible"] = False
                else:
                    item["return_status"] = None
                    item["return_eligible"] = return_allowed

        return orders_res.data

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/me/{order_id}", response_model=Order)
async def get_my_single_order(
    order_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    try:
        res = (
            supabase
            .table("orders")
            .select(
                """
                *,
                order_items(
                    *,
                    products(product_name,category,sub_category,images),
                    returns(status)
                )
                """
            )
            .eq("user_id", str(current_user.id))
            .eq("order_id", order_id)
            .single()
            .execute()
        )

        if not res.data:
            raise HTTPException(status_code=404, detail="Order not found")

        o = res.data
        now = datetime.now(timezone.utc)

        return_allowed = (
            o.get("delivery_date") is not None
            and o.get("return_valid_till") is not None
            and now <= datetime.fromisoformat(o["return_valid_till"])
        )

        for item in o["order_items"]:
            if item.get("returns"):
                item["return_status"] = item["returns"][0]["status"]
                item["return_eligible"] = False
            else:
                item["return_status"] = None
                item["return_eligible"] = return_allowed

            item.pop("returns", None)

        o["return_allowed"] = return_allowed

        return o

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.put("/orders/{order_id}", response_model=Order)
async def update_order(
    order_id: int,
    order_update: OrderUpdate,
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Update opt_out_delivery.
    """
    try:
        # check order
        existing_res = (
            supabase.table("orders")
            .select("*")
            .eq("order_id", order_id)
            .eq("user_id", str(current_user.id))
            .execute()
        )

        if not existing_res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
            )

        # update
        update_data = {"opt_out_delivery": order_update.opt_out_delivery}

        res = (
            supabase.table("orders")
            .update(update_data)
            .eq("order_id", order_id)
            .execute()
        )

        if not res.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Update failed",
            )

        # fetch updated
        final_res = (
            supabase.table("orders")
            .select("*, order_items(*, products(product_name,category, sub_category, images))")
            .eq("order_id", order_id)
            .execute()
        )

        if not final_res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found after update",
            )

        return final_res.data[0]

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/payment/verify")
async def verify_payment(
    data: PaymentVerificationRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Verify a Razorpay payment signature.
    """
    
    # 1. Check if order exists
    try:
        order_res = supabase.table("orders").select("*").eq("order_id", data.order_id).eq("user_id", str(current_user.id)).single().execute()
        if not order_res.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        order = order_res.data
        if order["payment_status"] == "Completed":
            return {"status": "success", "message": "Payment already verified"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error fetching order: {e}")

    # 2. Verify Signature
    try:
        params_dict = {
            'razorpay_order_id': data.razorpay_order_id,
            'razorpay_payment_id': data.razorpay_payment_id,
            'razorpay_signature': data.razorpay_signature
        }
        razorpay_client.utility.verify_payment_signature(params_dict)
    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Payment verification failed: Invalid signature")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Verification error: {e}")

    # 3. Update DB (order confirmation + coupon usage)
    try:
        # 3️⃣.1 Mark order as completed (idempotent)
        update_res = (
            supabase
            .table("orders")
            .update(
                {
                    "payment_status": "Completed",
                    "order_status": "Confirmed",
                    "razorpay_payment_id": data.razorpay_payment_id,
                }
            )
            .eq("order_id", data.order_id)
            .neq("payment_status", "Completed")   # 👈 VERY IMPORTANT
            .execute()
        )

        # 3️⃣.2 Increment coupon usage ONLY if order was just completed
        if update_res.data and len(update_res.data) > 0:
            order_row = update_res.data[0]

            if order_row.get("coupon_id"):
                supabase.table("coupons").update(
                    {"used_count": supabase.literal("used_count + 1")}
                ).eq("coupon_id", order_row["coupon_id"]).execute()

                print(f"Coupon {order_row['coupon_id']} usage incremented")

        return {"status": "success", "message": "Payment verified and order confirmed"}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DB update failed: {e}"
        )

    


# --- UPDATED ENDPOINT: Download Invoice (With Payment Check) ---
@router.get("/orders/{order_id}/invoice")
async def get_order_invoice(order_id: int, current_user: UserResponse = Depends(get_current_user)):
    """
    Generate and download a PDF invoice for a specific order.
    Only allows download if payment_status is 'Completed'.
    """
    try:
        # 1. Fetch Order details
        order_res = supabase.table("orders").select("*, order_items(*, products(product_name, category))").eq("order_id", order_id).eq("user_id", str(current_user.id)).execute()
        
        if not order_res.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        
        order_data = order_res.data[0]

        # --- NEW SECURITY CHECK ---
        # Prevent generating invoice for unpaid/pending orders
        if order_data.get("payment_status") != "Completed":
             raise HTTPException(
                 status_code=status.HTTP_400_BAD_REQUEST, 
                 detail="Invoice cannot be generated. Payment is not completed."
             )
        # --------------------------

        items_data = order_data.get('order_items', [])

        # 2. Fetch User Profile (for Address)
        user_res = supabase.table("profiles").select("*").eq("id", str(current_user.id)).execute()
        user_data = user_res.data[0] if user_res.data else {}

        # 3. Generate PDF
        pdf_bytes = generate_pdf_invoice(order_data, user_data, items_data)

        # 4. Return as downloadable file
        headers = {
            'Content-Disposition': f'attachment; filename="invoice_{order_id}.pdf"'
        }
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)

    except Exception as e:
        # If we manually raised the 400 above, allow it to pass through
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))




@router.post("/sync/supplier/{supplier_id}")
async def sync_supplier_products(
    supplier_id: str,
    x_sync_secret: str = Header(None)
):
    if x_sync_secret != SYNC_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    supplier_products = fetch_supplier_products()

    synced = 0
    for p in supplier_products:
        mapped = map_supplier_product(p, supplier_id)
        upsert_product(mapped)
        synced += 1

    return {"status": "ok", "synced": synced}




@router.get("/products/{product_id}/variants")
def get_product_variants(product_id: int):

    try:
        result = (
            supabase
            .table("product_variants")
            .select("variant_id, product_id, size, stock_quantity,mrp,price")
            .eq("product_id", product_id)
            .execute()
        )

        # result.data will always exist — may just be []
        return result.data

    except Exception as e:
        raise HTTPException(500, f"Failed to fetch variants: {e}")



# list all variants for debugging
@router.get("/variants")
def list_variants(product_id: int | None = None):
    """
    List all variants, or only variants for a specific product_id.
    """

    try:
        query = (
            supabase
            .table("product_variants")
            .select("variant_id, product_id, size, stock_quantity, mrp, price")
        )

        if product_id is not None:
            query = query.eq("product_id", product_id)

        result = (
            query
            .order("product_id")
            .order("size")
            .execute()
        )

        return result.data   # Safe — may be [] but won't crash

    except Exception as e:
        raise HTTPException(500, f"Failed to fetch variants: {e}")



#  to fetch one specific size+color
@router.get("/variants/{variant_id}")
def get_variant(variant_id: int):

    try:
        result = (
            supabase
            .table("product_variants")
            .select("variant_id, product_id, size, stock_quantity, mrp, price")
            .eq("variant_id", variant_id)
            .single()
            .execute()
        )

        if not result.data:
            raise HTTPException(404, "Variant not found")

        return result.data

    except Exception as e:
        raise HTTPException(500, f"Failed to fetch variant: {e}")



@router.get("/suppliers", response_model=List[Supplier])
async def get_suppliers():
    try:
        res = supabase.table("suppliers").select("*").execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    


@router.get("/brands", response_model=List[BrandResponse])
def get_brands():
    res = (
        supabase.table("brands").select("*").execute()
    )

    if not res.data:
        return []

    return res.data


@router.get("/categories", response_model=List[CategoryResponse])
def get_categories(segment: Optional[str] = Query(default=None)):
    try:
        query = supabase.table("categories").select("*")

        if segment:
            query = query.eq("segment", segment)

        res = query.execute()

        return res.data or []

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch categories: {str(e)}")



@router.post("/partners", response_model=PartnerResponse)
def submit_partner_application(payload: PartnerCreate):
    try:
        res = supabase.table("partners").insert(payload.model_dump()).execute()

        if not res.data:
            raise HTTPException(status_code=400, detail="Failed to submit application")

        return res.data[0]

    except Exception as e:
        msg = str(e)

        # ✅ Unique constraint violation
        if "duplicate key value violates unique constraint" in msg:
            raise HTTPException(
                status_code=409,
                detail="Application already exists with this email"
            )

        raise HTTPException(status_code=500, detail=msg)



# ✅ Get All Partner Applications (Admin use)
@router.get("/partners", response_model=list[PartnerResponse])
def get_all_partner_applications():
    res = supabase.table("partners").select("*").order("created_at", desc=True).execute()
    return res.data


@router.post("/partners/coupon", response_model=CouponGenerateResponse)
async def generate_coupon(
    payload: CouponGenerateRequest,
    user: UserResponse = Depends(get_current_user)
):
    # 1️⃣ Resolve partner (DD)
    partner_resp = (
        supabase
        .table("partners")
        .select("partner_id, full_name")
        .eq("email_id", user.email)
        .maybe_single()
        .execute()
    )

    if not partner_resp or not partner_resp.data:
        raise HTTPException(status_code=403, detail="Not a registered DD")

    partner = partner_resp.data
    partner_id = partner["partner_id"]
    dd_prefix = partner["full_name"].strip().upper()[:4]

    # 2️⃣ Decide UNIVERSAL vs BRAND
    is_universal = (
        payload.brand_code is None
        or payload.brand_code.strip().upper() == "QDIO"
    )

    # ------------------------------------------------
    # UNIVERSAL COUPON (QDIO)
    # ------------------------------------------------
    if is_universal:
        brand_resp = (
            supabase
            .table("brands")
            .select("brand_id")
            .eq("brand_code", "QDIO")
            .maybe_single()
            .execute()
        )

        if not brand_resp or not brand_resp.data:
            raise HTTPException(status_code=500, detail="QDIO  brand not configured")

        brand_id = brand_resp.data["brand_id"]
        brand_name = "All Brands"
        brand_code = "QDIO"

    # ------------------------------------------------
    # BRAND-SPECIFIC COUPON
    # ------------------------------------------------
    else:
        brand_resp = (
            supabase
            .table("brands")
            .select("brand_id, brand_name, brand_code")
            .eq("brand_code", payload.brand_code.upper())
            .maybe_single()
            .execute()
        )

        if not brand_resp or not brand_resp.data:
            raise HTTPException(status_code=404, detail="Invalid brand code")

        brand = brand_resp.data
        brand_id = brand["brand_id"]
        brand_name = brand["brand_name"]
        brand_code = brand["brand_code"]

    # ------------------------------------------------
    # 3️⃣ Check existing coupon FIRST
    # ------------------------------------------------
    existing_resp = (
        supabase
        .table("coupons")
        .select("*")
        .eq("partner_id", partner_id)
        .eq("brand_id", brand_id)
        .maybe_single()
        .execute()
    )

    if existing_resp and existing_resp.data:
        coupon = existing_resp.data

        offer = (
            supabase
            .table("offers")
            .select("offer_name, discount_type, discount_value")
            .eq("offer_id", coupon["offer_id"])
            .single()
            .execute()
        ).data

    else:
        # ------------------------------------------------
        # 4️⃣ Resolve OFFER
        # ------------------------------------------------
        if is_universal:
            offer_resp = (
                supabase
                .table("offers")
                .select("offer_id, offer_name, discount_type, discount_value")
                .eq("is_active", True)
                .eq("offer_type", "coupon")
                .lte("min_quantity", 1)
                .order("discount_value", desc=True)
                .limit(1)
                .maybe_single()
                .execute()
            )
        else:
            offer_resp = (
                supabase
                .table("brand_offer_active_view")
                .select("offer_id, offer_name, discount_type, discount_value")
                .eq("brand_id", brand_id)
                .maybe_single()
                .execute()
            )

        if not offer_resp or not offer_resp.data:
            raise HTTPException(status_code=400, detail="No active offer available")

        offer = offer_resp.data

        coupon_code = (
            f"QDIO{dd_prefix}{int(offer['discount_value'])}"
            if is_universal
            else f"{brand_code}{dd_prefix}{int(offer['discount_value'])}"
        )


        insert_resp = (
            supabase
            .table("coupons")
            .insert({
                "coupon_code": coupon_code,
                "partner_id": partner_id,
                "brand_id": brand_id,
                "offer_id": offer["offer_id"],
            })
            .execute()
        )

        if not insert_resp or not insert_resp.data:
            raise HTTPException(status_code=500, detail="Failed to create coupon")

        coupon = insert_resp.data[0]

    # ------------------------------------------------
    # 5️⃣ RESPONSE
    # ------------------------------------------------
    return {
        "coupon_code": coupon["coupon_code"],
        "brand_name": brand_name,
        "brand_code": brand_code,
        "offer_name": offer["offer_name"],
        "discount_type": offer["discount_type"],
        "discount_value": offer["discount_value"],
        "used_count": coupon["used_count"],
    }



@router.post("/coupons/validate", response_model=CouponValidateResponse)
async def validate_coupon(payload: CouponValidateRequest):
    variant_ids = [item.variant_id for item in payload.cart_items]

    resp = supabase.rpc(
        "validate_coupon_for_cart",
        {
            "p_coupon_code": payload.coupon_code,
            "p_variant_ids": variant_ids,
        }
    ).execute()

    if not resp or not resp.data:
        return {
            "valid": False,
            "coupon_id": "",
            "partner_id": "",
            "message": "Validation failed",
        }

    return resp.data[0]



# to convert UTC to IST
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def to_ist(dt):
    if dt is None:
        return None
    
    if isinstance(dt, str):
        # Handles "2026-01-30T09:50:53.338064Z"
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))

    return dt.astimezone(IST)



@router.post("/returns", status_code=201)
async def create_return(
    payload: ReturnCreate,
    current_user: UserResponse = Depends(get_current_user)
):
    try:
        # 1️⃣ Fetch order
        order_res = (
            supabase
            .table("orders")
            .select("order_id, user_id, delivery_date, return_valid_till")
            .eq("order_id", payload.order_id)
            .eq("user_id", str(current_user.id))
            .single()
            .execute()
        )

        if not order_res.data:
            raise HTTPException(status_code=404, detail="Order not found")

        order = order_res.data

        # 2️⃣ Validate delivery & return window
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        if not order["delivery_date"]:
            raise HTTPException(status_code=400, detail="Order not delivered yet")

        if now > datetime.fromisoformat(order["return_valid_till"]):
            raise HTTPException(status_code=400, detail="Return window expired")

        # 3️⃣ Validate product belongs to order
        item_res = (
            supabase
            .table("order_items")
            .select("variant_id, product_id, products(product_name)")
            .eq("order_id", payload.order_id)
            .eq("variant_id", payload.variant_id)
            .single()
            .execute()
        )

        if not item_res.data:
            raise HTTPException(status_code=400, detail="Variant not part of order")


        product_name = item_res.data["products"]["product_name"]

        # 4️⃣ Prevent duplicate return
        existing = (
            supabase
            .table("returns")
            .select("return_id")
            .eq("order_id", payload.order_id)
            .eq("variant_id", payload.variant_id)
            .execute()
        )

        if existing.data:
            raise HTTPException(status_code=400, detail="Return already requested")

        # 5️⃣ Create return
        insert_data = {
            "order_id": payload.order_id,
            "user_id": str(current_user.id),
            "product_id": item_res.data["product_id"],
            "variant_id": payload.variant_id,
            "product_name": item_res.data["products"]["product_name"],
            "quantity": payload.quantity,
            "return_type": payload.return_type.value,
            "reason": payload.reason,
            "pickup_address": payload.pickup_address,
        }


        res = supabase.table("returns").insert(insert_data).execute()

        return {
            "message": "Return request created",
            "return_id": res.data[0]["return_id"],
            "status": res.data[0]["status"],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/returns", response_model=list[ReturnResponse])
async def get_my_returns(
    order_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    res = (
        supabase
        .table("returns")
        .select("*")
        .eq("order_id", order_id)
        .eq("user_id", str(current_user.id))
        .execute()
    )

    for r in res.data:
        r["initiated_at"] = to_ist(r["initiated_at"])
        r["updated_at"] = to_ist(r["updated_at"])

    return res.data


@router.patch("/admin/returns/{return_id}", response_model=ReturnResponse)
async def update_return_status(
    return_id: int,
    payload: ReturnUpdate
):
    res = (
        supabase
        .table("returns")
        .update({
            "status": payload.status.value,   
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
        .eq("return_id", return_id)
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=404, detail="Return not found")

    result = res.data[0]

    result["initiated_at"] = to_ist(result["initiated_at"])
    result["updated_at"] = to_ist(result["updated_at"])

    return result



@router.get("/admin/returns", response_model=list[ReturnResponse])
async def get_all_returns(
    status: ReturnStatusEnum | None = None
):
    query = supabase.table("returns").select("*")

    if status:
        query = query.eq("status", status.value)

    res = query.order("initiated_at", desc=True).execute()

    # Convert to IST
    for r in res.data:
        r["initiated_at"] = to_ist(r["initiated_at"])
        r["updated_at"] = to_ist(r["updated_at"])

    return res.data




now = datetime.now(timezone.utc)
return_valid_till = now + timedelta(days=7)


@router.post("/admin/orders/{order_id}/delivery-status")
async def update_delivery_status(
    order_id: int,
    payload: DeliveryStatusCreate,
):
    # 1️⃣ Check order exists
    order_res = (
        supabase
        .table("orders")
        .select("order_id, delivery_date")
        .eq("order_id", order_id)
        .single()
        .execute()
    )

    if not order_res.data:
        raise HTTPException(status_code=404, detail="Order not found")

    # 2️⃣ Insert into delivery_status log
    supabase.table("delivery_status").insert({
        "order_id": order_id,
        "delivery_partner_id": payload.delivery_partner_id,
        "status": payload.status.value,   # IMPORTANT
        "remarks": payload.remarks
    }).execute()

    # 3️⃣ If Delivered → update orders table
    if payload.status == DeliveryStatusEnum.DELIVERED:
        if order_res.data["delivery_date"] is None:
            now = datetime.now(timezone.utc)
            supabase.table("orders").update({
                "delivery_date": now.isoformat(),
                "return_valid_till": (now + timedelta(days=7)).isoformat()
            }).eq("order_id", order_id).execute()

    return {
        "message": "Delivery status updated successfully",
        "status": payload.status.value
    }
