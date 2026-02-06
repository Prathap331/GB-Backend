# routers.py
from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from typing import List, Optional
from datetime import datetime, timedelta, timezone
import uuid
from fastapi import Header, HTTPException
import json
import razorpay
import asyncio


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
    AdminCouponCreateRequest, BrandResponse, CategoryResponse, DeliveryStatusCreate, DeliveryStatusEnum, PartnerActivateRequest, PartnerCreate, PartnerDashboardResponse, PartnerLoginRequest,  PartnerResponse, PartnerSignupRequest, Product, ProductUpdate, 
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
    partner_id = None

    # -------------------------
    # 1️⃣ Validate partner_code (SERVER DB – service role)
    # -------------------------
    if user.partner_code:
        partner_res = (
            supabase
            .table("partners")
            .select("partner_id")
            .eq("partner_code", user.partner_code.upper())
            .maybe_single()
            .execute()
        )

        if not partner_res or not partner_res.data:
            raise HTTPException(status_code=400, detail="Invalid partner code")

        partner_id = partner_res.data["partner_id"]

    print("DEBUG | partner_code:", user.partner_code)
    print("DEBUG | partner_id:", partner_id)

    # -------------------------
    # 2️⃣ Auth signup (PUBLIC – anon client)
    # -------------------------
    res = supabase_anon.auth.sign_up({
        "email": user.email,
        "password": user.password,
        "options": {
            "data": {
                "full_name": user.full_name,
                "phone": user.phone_number
            }
        }
    })

    # IMPORTANT: signup either succeeds or raises
    if not res or not res.user:
        raise HTTPException(status_code=400, detail="Signup failed")

    user_id = res.user.id
    print("DEBUG | auth user_id:", user_id)

    # -------------------------
    # 3️⃣ WAIT for auth.users commit (VERY IMPORTANT)
    # -------------------------
    # Email verification ON → needs more time
    await asyncio.sleep(1.0)

    # -------------------------
    # 4️⃣ Upsert profile (SERVER DB – service role)
    #     ❗ NEVER fail signup if this fails
    # -------------------------
    profile_payload = {
        "id": user_id,
        "full_name": user.full_name,
        "phone_number": user.phone_number,
        "email": user.email,
        "is_partner": bool(partner_id),
        "partner_id": partner_id,
    }

    try:
        upsert_res = (
            supabase
            .table("profiles")
            .upsert(profile_payload, on_conflict="id")
            .execute()
        )
        print("DEBUG | profile upsert response:", upsert_res.data)

    except Exception as e:
        # ❗ DO NOT raise — auth already succeeded
        print("PROFILE UPSERT FAILED (will retry later):", e)

    # -------------------------
    # 5️⃣ Always return success if auth succeeded
    # -------------------------
    return UserResponse(
        id=user_id,
        email=user.email,
        created_at=res.user.created_at
    )


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


@router.post("/partners/activate")
async def activate_partner(
    payload: PartnerActivateRequest,
    user: UserResponse = Depends(get_current_user)
):
    # 1️⃣ Validate partner_id
    partner_res = (
        supabase
        .table("partners")
        .select("partner_id")
        .eq("partner_id", str(payload.partner_id))
        .maybe_single()
        .execute()
    )

    if not partner_res or not partner_res.data:
        raise HTTPException(400, "Invalid partner_id")

    # 2️⃣ Fetch profile
    profile_res = (
        supabase
        .table("profiles")
        .select("id, is_partner")
        .eq("id", str(user.id))
        .maybe_single()
        .execute()
    )

    if not profile_res or not profile_res.data:
        raise HTTPException(404, "Profile not found")

    if profile_res.data["is_partner"]:
        raise HTTPException(409, "Already a partner")

    # 3️⃣ Update profile
    supabase.table("profiles").update({
        "is_partner": True,
        "partner_id": str(payload.partner_id)
    }).eq("id", str(user.id)).execute()

    return {
        "status": "success",
        "message": "Partner access activated"
    }


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

@router.get("/auth/me")
async def me(user: UserResponse = Depends(get_current_user)):
    profile = {}

    res = (
        supabase
        .table("profiles")
        .select("full_name, email, is_partner, partner_id")
        .eq("id", str(user.id))
        .maybe_single()
        .execute()
    )

    if res and res.data:
        profile = res.data

    return {
        "id": user.id,
        "email": user.email,
        **profile
    }


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




def ist_to_utc(dt):
    if dt.tzinfo is None:
        return IST.localize(dt).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


@router.post("/orders/price-preview")
async def price_preview(order: OrderCreate):

    validated_items = []

    # ---------------------------------
    # 1️⃣ Validate items (SOURCE OF TRUTH)
    # ---------------------------------
    for item in order.items:
        variant = (
            supabase.table("product_variants")
            .select("variant_id, product_id, stock_quantity")
            .eq("variant_id", item.variant_id)
            .single()
            .execute()
        ).data

        if not variant:
            raise HTTPException(400, "Invalid variant")

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

    # ---------------------------------
    # 2️⃣ BASE TOTALS (NO DISCOUNTS)
    # ---------------------------------
    subtotal = round(sum(i["subtotal"] for i in validated_items), 2)

    pricing = {
        "subtotal": subtotal,
        "discount": 0.0,
        "coupon_discount": 0.0,
        "total_discount": 0.0,
        "gst": 0.0,
        "shipping_fee": 0.0,
        "cod_fee": 0.0,
        "total": 0.0,
    }

    # ---------------------------------
    # 3️⃣ COUPON VALIDATION & APPLY
    # ---------------------------------
    if order.coupon_code:
        coupon_res = (
            supabase.table("coupons")
            .select("""
                coupon_id,
                offer_scope,
                brand_id,
                partner_id,
                discount_type,
                discount_value,
                min_quantity,
                start_date,
                end_date,
                is_active,
                used_count
            """)
            .eq("coupon_code", order.coupon_code.upper())
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        # print("Coupon fetch result:", coupon_res)

        if not coupon_res or not coupon_res.data:
            raise HTTPException(400, "Invalid or inactive coupon")
            
        coupon = coupon_res.data
        
        now = datetime.now(timezone.utc)

        start_date = datetime.fromisoformat(coupon["start_date"])
        end_date = datetime.fromisoformat(coupon["end_date"])

        # make sure both are timezone-aware
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        if not (start_date <= now <= end_date):
            raise HTTPException(400, "Coupon expired")


        # quantity check
        total_qty = sum(i["quantity"] for i in validated_items)
        if total_qty < coupon["min_quantity"]:
            raise HTTPException(400, "Minimum quantity not met")

        # scope check
        if coupon["offer_scope"] == "brand":
            cart_brands = {i["brand_id"] for i in validated_items}
            if coupon["brand_id"] not in cart_brands:
                raise HTTPException(400, "Coupon not applicable for this brand")

        # apply discount
        if coupon["discount_type"] == "percentage":
            coupon_discount = round(
                subtotal * (coupon["discount_value"] / 100), 2
            )
        else:
            coupon_discount = round(coupon["discount_value"], 2)

        pricing["coupon_discount"] = coupon_discount
        pricing["discount"] = coupon_discount
        pricing["total_discount"] = coupon_discount

    # ---------------------------------
    # 4️⃣ FINAL TOTALS
    # ---------------------------------
    discounted = round(subtotal - pricing["total_discount"], 2)

    gst = round(discounted * 0.05, 2)
    final = round(discounted + gst, 2)

    shipping = 49.0 if final < 499 else 0.0
    final += shipping

    cod_fee = 0.0
    if order.payment_method == "COD":
        cod_fee = max(40.0, round(final * 0.02, 2))
        final += cod_fee

    pricing.update({
        "gst": gst,
        "shipping_fee": shipping,
        "cod_fee": cod_fee,
        "total": round(final, 2)
    })

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


    # 2️⃣ VALIDATE ITEMS & STOCK
    try:
        if not order.items:
            raise HTTPException(400, "No items in order")

        validated_items = []
        subtotal = 0.0

        for item in order.items:
            variant_res = (
                supabase.table("product_variants")
                .select("variant_id, product_id, stock_quantity, size")
                .eq("variant_id", item.variant_id)
                .maybe_single()
                .execute()
            )

            if not variant_res or not variant_res.data:
                raise HTTPException(400, "Invalid variant")

            v = variant_res.data


            if v["stock_quantity"] < item.quantity:
                raise HTTPException(
                    400, f"Insufficient stock for size {v['size']}"
                )

            product_res = (
                supabase.table("products")
                .select("product_id, brand_id, price, supplier_id, supplier_product_id, color")
                .eq("product_id", v["product_id"])
                .maybe_single()
                .execute()
            )

            if not product_res or not product_res.data:
                raise HTTPException(400, "Invalid product")

            p = product_res.data


            price_per_unit = float(p["price"])
            line_total = price_per_unit * item.quantity
            subtotal += line_total

            validated_items.append({
                "variant_id": v["variant_id"],
                "product_id": p["product_id"],
                "brand_id": p["brand_id"],
                "quantity": item.quantity,
                "price_per_unit": price_per_unit,
                "subtotal": line_total,
                "new_stock": v["stock_quantity"] - item.quantity,
                "supplier_id": p["supplier_id"],
                "supplier_product_id": p["supplier_product_id"],
                "size": v["size"],
                "color": p["color"],
            })

        subtotal = round(subtotal, 2)
        total_qty = sum(i["quantity"] for i in validated_items)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Item validation error: {e}")

    # =====================================================
    # 3️⃣ COUPON VALIDATION
    # =====================================================
    discount = 0.0
    coupon_data = None

    if order.coupon_code:
        coupon_res = (
            supabase.table("coupons")
            .select("""
                coupon_id,
                offer_scope,
                brand_id,
                partner_id,
                discount_type,
                discount_value,
                min_quantity,
                start_date,
                end_date,
                is_active,
                used_count
            """)
            .eq("coupon_code", order.coupon_code.upper())
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        # print("Coupon fetch result:", coupon_res)


        if not coupon_res or not coupon_res.data:
            raise HTTPException(400, "Invalid or inactive coupon")
        
        coupon = coupon_res.data    

        now = datetime.now(timezone.utc)

        start_date = datetime.fromisoformat(coupon["start_date"])
        end_date = datetime.fromisoformat(coupon["end_date"])

        # make sure both are timezone-aware
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)

        if not (start_date <= now <= end_date):
            raise HTTPException(400, "Coupon expired")


        if total_qty < coupon["min_quantity"]:
            raise HTTPException(400, "Minimum quantity not met")

        if coupon["offer_scope"] == "brand":
            cart_brands = {i["brand_id"] for i in validated_items}
            if coupon["brand_id"] not in cart_brands:
                raise HTTPException(400, "Coupon not applicable for this brand")

        if coupon["discount_type"] == "percentage":
            discount = round(subtotal * (coupon["discount_value"] / 100), 2)
        else:
            discount = round(coupon["discount_value"], 2)

        coupon_data = coupon

    # =====================================================
    # 4️⃣ FINAL TOTALS
    # =====================================================
    discounted = round(subtotal - discount, 2)

    gst_amount = round(discounted * 0.05, 2)
    total = discounted + gst_amount

    shipping_fee = 49.0 if total < 499 else 0.0
    total += shipping_fee

    cod_fee = 0.0
    if order.payment_method == "COD":
        cod_fee = max(40.0, round(total * 0.02, 2))
        total += cod_fee

    grand_total = round(total, 2)


    contest_id = uuid.uuid4().hex
    lucky_numbers = generate_unique_lucky_numbers(int(subtotal // 1000))

    # =====================================================
    # 5️⃣ CREATE ORDER
    # =====================================================
    try:
        order_data = {
            "user_id": str(current_user.id),
            "total_amount": grand_total,
            "payment_method": order.payment_method,
            "delivery_address": delivery_address,
            "payment_status": "Pending",
            "order_status": "Pending",
            "contest_id": contest_id,
            "lucky_number": lucky_numbers,
            "coupon_id": coupon_data["coupon_id"] if coupon_data else None,
            "partner_id": coupon_data["partner_id"] if coupon_data else None,
            "opt_out_delivery": order.opt_out_delivery,
        }

        order_res = supabase.table("orders").insert(order_data).execute()
        new_order = order_res.data[0]
        new_order_id = new_order["order_id"]

    except Exception as e:
        raise HTTPException(500, f"Order creation failed: {e}")

    # =====================================================
    # 6️⃣ ORDER ITEMS
    # =====================================================
    try:
        items_payload = []
        for i in validated_items:
            items_payload.append({
                "order_id": new_order_id,
                "product_id": i["product_id"],
                "variant_id": i["variant_id"],
                "quantity": i["quantity"],
                "price_per_unit": i["price_per_unit"],
                "subtotal": i["subtotal"],
                "supplier_id": i["supplier_id"],
                "supplier_product_id": i["supplier_product_id"],
                "size": i["size"],
                "color": i["color"],
            })

        supabase.table("order_items").insert(items_payload).execute()

    except Exception as e:
        supabase.table("orders").delete().eq("order_id", new_order_id).execute()
        raise HTTPException(500, f"Order items failed: {e}")
    


    # 7️⃣ RAZORPAY LOGIC (unchanged)
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



    #  DEDUCT STOCK PER VARIANT
    for item in validated_items:
        (
            supabase
            .table("product_variants")
            .update({"stock_quantity": item["new_stock"]})
            .eq("variant_id", item["variant_id"])
            .execute()
        )

    # =====================================================
    # 9️⃣ COUPON USAGE (COD ONLY)
    # =====================================================
    if coupon_data and order.payment_method == "COD":
        supabase.table("coupons").update({
            "used_count": coupon_data["used_count"] + 1
        }).eq("coupon_id", coupon_data["coupon_id"]).execute()

    
    # =====================================================
    # 🔥 PARTNER DASHBOARD UPDATE (COD ONLY)
    # =====================================================
    if (
        coupon_data
        and order.payment_method == "COD"
        and coupon_data.get("partner_id")
    ):
        # total products sold
        products_sold = sum(item["quantity"] for item in validated_items)

        supabase.table("partners_profiles").update({
            "total_orders": supabase.literal("total_orders + 1"),
            "products_sold": supabase.literal(f"products_sold + {products_sold}"),
            "total_coupon_usage": supabase.literal("total_coupon_usage + 1"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq(
            "partner_id", coupon_data["partner_id"]
        ).execute()


    # 10. RETURN FINAL ORDER
    order_res = (
        supabase.table("orders")
        .select("*, order_items(*, products(product_name, category, sub_category, images))")
        .eq("order_id", new_order_id)
        .maybe_single()
        .execute()
    )

    if not order_res or not order_res.data:
        raise HTTPException(500, "Order fetch failed")

    final_order = Order.model_validate(order_res.data)


    if razorpay_order_id:
        final_order.razorpay_order_id = razorpay_order_id
        final_order.razorpay_key_id = RAZORPAY_KEY_ID

    final_order.shipping_fee = shipping_fee
    final_order.gst_amount = gst_amount
    final_order.cod_fee = cod_fee
    final_order.coupon_discount = discount
    final_order.total_discount = discount

    return final_order



@router.get("/orders")
async def get_orders(
    partner_id: Optional[str] = Query(None, description="Filter orders by partner_id")
):
    """
    Get all orders.
    Optionally filter by partner_id (DD).
    """

    query = (
        supabase
        .table("orders")
        .select("""
            *,
            order_items(
                *,
                products(
                    product_name,
                    category,
                    sub_category,
                    images
                )
            )
        """)
        .order("created_at", desc=True)
    )

    # 🔹 Apply filter only if partner_id is provided
    if partner_id:
        query = query.eq("partner_id", partner_id)

    res = query.execute()

    return res.data



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
            .maybe_single()
            .execute()
        )

        if not res or not res.data:
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
            .neq("payment_status", "Completed")   
            .execute()
        )

        # 🔐 Only if this call actually updated the order
        if update_res.data and len(update_res.data) > 0:
            updated_order = update_res.data[0]

            # =================================================
            # 3️⃣.1 Coupon usage
            # =================================================
            if updated_order.get("coupon_id"):
                coupon_res = (
                    supabase
                    .table("coupons")
                    .select("coupon_id, partner_id")
                    .eq("coupon_id", updated_order["coupon_id"])
                    .maybe_single()
                    .execute()
                )

                if coupon_res and coupon_res.data:
                    coupon = coupon_res.data

                    # increment coupon usage
                    supabase.table("coupons").update({
                        "used_count": supabase.literal("used_count + 1")
                    }).eq("coupon_id", coupon["coupon_id"]).execute()

                    # =================================================
                    # 3️⃣.2 Partner dashboard update (ONLY if partner coupon)
                    # =================================================
                    if coupon.get("partner_id"):
                        items_res = (
                            supabase
                            .table("order_items")
                            .select("quantity")
                            .eq("order_id", data.order_id)
                            .execute()
                        )

                        products_sold = sum(
                            i["quantity"] for i in (items_res.data or [])
                        )

                        supabase.table("partners_profiles").update({
                            "total_orders": supabase.literal("total_orders + 1"),
                            "products_sold": supabase.literal(f"products_sold + {products_sold}"),
                            "total_coupon_usage": supabase.literal("total_coupon_usage + 1"),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }).eq(
                            "partner_id", coupon["partner_id"]
                        ).execute()

        return {"status": "success", "message": "Payment verified and order confirmed"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB update failed: {e}")

    


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


@router.post("/admin/coupons")
async def create_coupon_admin(payload: AdminCouponCreateRequest):
    try:
        # =====================================================
        # 1️⃣ Resolve BRAND
        # =====================================================
        brand_id = None
        brand_code = "QDIO"   # default for universal

        if payload.offer_scope == "brand":
            if not payload.brand_code:
                raise HTTPException(400, "brand_code required for brand coupons")

            brand_res = (
                supabase
                .table("brands")
                .select("brand_id, brand_code")
                .eq("brand_code", payload.brand_code.upper())
                .maybe_single()
                .execute()
            )

            if not brand_res or not brand_res.data:
                raise HTTPException(400, "Invalid brand_code")

            brand_id = brand_res.data["brand_id"]
            brand_code = brand_res.data["brand_code"]

        # =====================================================
        # 2️⃣ Resolve PARTNER (only if partner coupon)
        # =====================================================
        partner_id = None
        partner_code = ""

        if payload.offer_by == "partner":
            if not payload.partner_id:
                raise HTTPException(400, "partner_id required for partner coupons")

            partner_res = (
                supabase
                .table("partners")
                .select("partner_id, full_name")
                .eq("partner_id", str(payload.partner_id))
                .maybe_single()
                .execute()
            )

            if not partner_res or not partner_res.data:
                raise HTTPException(400, "Invalid partner_id")

            partner_id = partner_res.data["partner_id"]
            partner_code = (
                partner_res.data["full_name"]
                .replace(" ", "")
                .upper()[:4]
            )

        # =====================================================
        # 3️⃣ GENERATE COUPON CODE (AUTO ONLY)
        
        coupon_code = f"{brand_code}{partner_code}{int(payload.discount_value)}"

        # =====================================================
        # 4️⃣ INSERT COUPON
        # =====================================================
        insert_res = (
            supabase
            .table("coupons")
            .insert({
                "coupon_code": coupon_code,
                "offer_by": payload.offer_by,
                "offer_scope": payload.offer_scope,
                "brand_id": brand_id,
                "partner_id": partner_id,
                "discount_type": payload.discount_type,
                "discount_value": payload.discount_value,
                "min_quantity": payload.min_quantity,
                "start_date": payload.start_date.isoformat(),
                "end_date": payload.end_date.isoformat(),
                "is_active": payload.is_active,
            })
            .execute()
        )

        if not insert_res or not insert_res.data:
            raise HTTPException(500, "Failed to create coupon")
        

        # =====================================================
        # 5️⃣ RESPONSE
        # =====================================================
        return {
            "status": "success",
            "coupon_code": coupon_code,
            "offer_by": payload.offer_by,
            "offer_scope": payload.offer_scope,
            "brand_id": brand_id,
            "partner_id": partner_id,
            "discount_type": payload.discount_type,
            "discount_value": payload.discount_value,
            "min_quantity": payload.min_quantity,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "is_active": payload.is_active,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Coupon creation failed: {e}")


@router.get("/coupons")
async def get_all_coupons():
    """
    Get all coupons.
    """

    try:
        res = (
            supabase
            .table("coupons")
            .select("""
                coupon_id,
                coupon_code,
                offer_by,
                offer_scope,
                brand_id,
                partner_id,
                discount_type,
                discount_value,
                min_quantity,
                used_count,
                start_date,
                end_date,
                is_active,
                created_at
            """)
            .order("created_at", desc=True)
            .execute()
        )

        return res.data

    except Exception as e:
        raise HTTPException(500, f"Failed to fetch coupons: {e}")


@router.get("/partners/coupons")
async def get_partner_coupons(
    user: UserResponse = Depends(get_current_user)
):
    # 1️⃣ Resolve partner
    partner_res = (
        supabase.table("partners")
        .select("partner_id")
        .eq("email_id", user.email)
        .maybe_single()
        .execute()
    )

    if not partner_res or not partner_res.data:
        raise HTTPException(403, "Not a registered partner")

    partner_id = partner_res.data["partner_id"]

    # 2️⃣ Fetch coupons
    coupons_res = (
        supabase.table("coupons")
        .select("""
            coupon_id,
            coupon_code,
            offer_scope,
            brand_id,
            discount_type,
            discount_value,
            min_quantity,
            start_date,
            end_date,
            is_active,
            created_at
        """)
        .eq("partner_id", partner_id)
        .eq("is_active", True)
        .order("created_at", desc=True)
        .execute()
    )

    if not coupons_res:
        raise HTTPException(500, "Failed to fetch coupons")

    return coupons_res.data or []




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

    

@router.get("/partners/dashboard")
async def partner_dashboard(
    user: UserResponse = Depends(get_current_user)
):
    try:
        # =====================================================
        # 1️⃣ AUTH SOURCE OF TRUTH → profiles table
        # =====================================================
        profile_res = (
            supabase
            .table("profiles")
            .select("""
                id,
                full_name,
                email,
                is_partner,
                partner_id
            """)
            .eq("id", str(user.id))
            .maybe_single()
            .execute()
        )

        if not profile_res or not profile_res.data:
            raise HTTPException(401, "Profile not found")

        profile = profile_res.data

        if not profile["is_partner"] or not profile["partner_id"]:
            raise HTTPException(403, "Not a partner account")

        partner_id = profile["partner_id"]

        # =====================================================
        # 2️⃣ ENSURE partners_profiles ROW EXISTS (AUTO-HEAL)
        # =====================================================
        partner_profile_res = (
            supabase
            .table("partners_profiles")
            .select("""
                id,
                partner_code,
                total_earnings
            """)
            .eq("id", str(user.id))
            .maybe_single()
            .execute()
        )

        if not partner_profile_res or not partner_profile_res.data:
            # auto-create partner profile if missing
            partner_profile_res = (
                supabase
                .table("partners_profiles")
                .insert({
                    "id": str(user.id),
                    "partner_id": partner_id,
                    "full_name": profile["full_name"],
                    "email": profile["email"],
                    "phone_number": None,
                })
                .execute()
            )

            partner_profile = partner_profile_res.data[0]
        else:
            partner_profile = partner_profile_res.data

        # =====================================================
        # 3️⃣ ACTIVE COUPONS + BRAND INFO
        # =====================================================
        coupons_res = (
            supabase
            .table("coupons")
            .select("""
                coupon_code,
                discount_type,
                discount_value,
                brands (
                    brand_name,
                    brand_logo
                )
            """)
            .eq("partner_id", partner_id)
            .eq("is_active", True)
            .execute()
        )

        coupons = coupons_res.data or []

        # =====================================================
        # 4️⃣ ORDERS USING PARTNER COUPONS
        # =====================================================
        orders_res = (
            supabase
            .table("orders")
            .select("order_id, total_amount")
            .eq("partner_id", partner_id)
            .eq("payment_status", "Completed")
            .execute()
        )

        orders = orders_res.data or []
        total_sale_value = sum(o["total_amount"] for o in orders)

        # =====================================================
        # 5️⃣ PRODUCTS SOLD
        # =====================================================
        products_sold = 0
        if orders:
            order_ids = [o["order_id"] for o in orders]

            items_res = (
                supabase
                .table("order_items")
                .select("quantity")
                .in_("order_id", order_ids)
                .execute()
            )

            products_sold = sum(
                i["quantity"] for i in (items_res.data or [])
            )

        # =====================================================
        # 6️⃣ RESPONSE
        # =====================================================
        return {
            "partner_id": partner_id,
            "partner_code": partner_profile.get("partner_code"),
            "partner_name": profile["full_name"],

            "total_sale_value": round(total_sale_value, 2),
            "your_earnings": float(partner_profile.get("total_earnings", 0)),

            "products_sold": products_sold,
            "active_coupons": len(coupons),

            "coupons": [
                {
                    "coupon_code": c["coupon_code"],
                    "discount_type": c["discount_type"],
                    "discount_value": c["discount_value"],
                    "brand_name": c["brands"]["brand_name"] if c["brands"] else None,
                    "brand_logo": c["brands"]["brand_logo"] if c["brands"] else None,
                }
                for c in coupons
            ],

            "partner_brands": list({
                c["brands"]["brand_name"]
                for c in coupons
                if c["brands"]
            }),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Dashboard fetch failed: {e}")
