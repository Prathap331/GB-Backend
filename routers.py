# routers.py
from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from typing import List
from datetime import datetime, timezone
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
    Product, ProductUpdate, 
    Order, OrderCreate, OrderUpdate,
    Profile, ProfileBase,
    DeliveryPartner,
    PaymentVerificationRequest, Supplier,
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

            if not profile_check.data:
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
        # READ as the user (RLS enforced)
        res = (
            supabase.table("profiles")
            .select("*")
            .eq("id", str(current_user.id))
            .maybe_single()
            .execute()
        )

        # --- AUTO CREATE PROFILE FOR GOOGLE USERS ---
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

            insert_res = supabase.table("profiles").insert(profile).execute()
            return insert_res.data[0]
        # -------------------------------------------

        return res.data

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print("PROFILE ERROR:", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))






@router.put("/profiles/me", response_model=Profile)
async def update_my_profile(profile: ProfileBase, current_user: UserResponse = Depends(get_current_user)):
    try:
        update_data = profile.model_dump(exclude_unset=True)
        if not update_data: raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No update data provided")
        update_data["updated_at"] = datetime.now().isoformat()
        supabase_anon.postgrest.auth(current_user.token)
        res = supabase_anon.table("profiles").update(update_data).eq("id", str(current_user.id)).execute()
        if not res.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found or update failed")
        return res.data[0]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

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

        return res.data

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

    for item in order.items:
        # get variant
        v = (
            supabase.table("product_variants")
            .select("variant_id, product_id, stock_quantity")
            .eq("variant_id", item.variant_id)
            .single()
            .execute()
        )

        variant = v.data

        # get product (for price)
        p = (
            supabase.table("products")
            .select("product_id, price")
            .eq("product_id", variant["product_id"])
            .single()
            .execute()
        )

        product = p.data

        price = float(product["price"])
        subtotal = price * item.quantity

        validated_items.append(
            {
                "variant_id": item.variant_id,
                "product_id": variant["product_id"],
                "quantity": item.quantity,
                "price_per_unit": price,
                "subtotal": subtotal,
            }
        )

    pricing = calculate_order_pricing(order, validated_items)

    return pricing



# --- Order Endpoints (UPDATED WITH RAZORPAY) ---


@router.post("/orders", response_model=Order)
async def create_order(
    order: OrderCreate,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Create a new order using variant_id (size/color).
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

            # 🔍 get variant (this contains stock + product_id)
            try:
                v = (
                    supabase.table("product_variants")
                    .select("variant_id, product_id, color, size, stock_quantity")
                    .eq("variant_id", variant_id)
                    .single()
                    .execute()
                )
            except Exception:
                raise HTTPException(404, f"Variant {variant_id} not found")

            if not v.data:
                raise HTTPException(404, f"Variant {variant_id} not found")

            variant = v.data

            if variant["stock_quantity"] < qty:
                raise HTTPException(
                    400,
                    f"Not enough stock for {variant['color']} / {variant['size']}",
                )

            # 💰 fetch price from product table
            try:
                p = (
                    supabase.table("products")
                    .select("product_id, price, supplier_id, supplier_product_id")
                    .eq("product_id", variant["product_id"])
                    .single()
                    .execute()
                )
            except Exception:
                raise HTTPException(404, f"Product {variant['product_id']} not found")
        

            product = p.data
            
            if not product:
                raise HTTPException(404, f"Product {variant['product_id']} not found")

            # 👇 SAFE PRICE CHECK
            price_raw = product.get("price")

            if price_raw is None:
                raise HTTPException(
                    400,
                    f"Product {product['product_id']} has no price available"
                )

            price_per_unit = round(float(price_raw), 2)
            subtotal = price_per_unit * qty
            total_amount += subtotal

            validated_items.append(
                {
                    "variant_id": variant_id,
                    "product_id": variant["product_id"],
                    "quantity": qty,
                    "price_per_unit": price_per_unit,
                    "subtotal": subtotal,
                    "new_stock": variant["stock_quantity"] - qty,
                    "supplier_id": product["supplier_id"],
                    "supplier_product_id": product["supplier_product_id"],
                }
            )

        # 🔢 shared pricing
        pricing = calculate_order_pricing(order, validated_items)

        grand_total = pricing["total"]
        gst_amount = pricing["gst"]
        shipping_fee = pricing["shipping_fee"]
        cod_fee = pricing["cod_fee"]

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

        order_res = supabase.table("orders").insert(order_data).execute()
        print("[ORDER CREATED RESPONSE]", order_res.data)

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

    # 4️⃣ CREATE ORDER ITEMS (store VARIANT_ID!)
    try:
        payload = []
        for item in validated_items:
            payload.append(
                {
                    "order_id": new_order_id,
                    "product_id": item["product_id"],
                    "variant_id": item["variant_id"],   # 👈 IMPORTANT
                    "quantity": item["quantity"],
                    "price_per_unit": item["price_per_unit"],
                    "subtotal": item["subtotal"],
                    "supplier_id": item["supplier_id"],
                    "supplier_product_id": item["supplier_product_id"],
                }
            )

        supabase.table("order_items").insert(payload).execute()
        print("[ORDER ITEMS INSERTED]", payload)


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
            print("[RAZORPAY ORDER CREATED]", razorpay_order_id)

            supabase.table("orders").update(
                {"razorpay_order_id": razorpay_order_id}
            ).eq("order_id", new_order_id).execute()

        except Exception as e:
            print("[RAZORPAY ERROR]", str(e))
            supabase.table("orders").delete().eq("order_id", new_order_id).execute()
            raise HTTPException(500, f"Razorpay creation failed: {e}")


    # 6️⃣ DEDUCT STOCK PER VARIANT
    for item in validated_items:
        
        update_res = (
            supabase
            .table("product_variants")
            .update({"stock_quantity": item["new_stock"]})
            .eq("variant_id", item["variant_id"])
            .execute()
        )

        
        

    # 7️⃣ RETURN FINAL ORDER
    full_order = (
        supabase.table("orders")
        .select("*, order_items(*, products(product_name, category, image_url))")
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

    return final_order



@router.get("/orders/me", response_model=List[Order])
async def get_my_orders(current_user: UserResponse = Depends(get_current_user)):
    try:
        # The query string here is critical. We ask for products explicitly.
        res = supabase.table("orders").select("*, order_items(*, products(product_name,category, image_url))").eq("user_id", str(current_user.id)).order("created_at", desc=True).execute()
        
        return [Order.model_validate(o) for o in res.data]
    
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/orders/me/{order_id}", response_model=Order)
async def get_my_single_order(order_id: int, current_user: UserResponse = Depends(get_current_user)):
    try:
        '''
        res = supabase.table("orders").select("*, order_items(*)").eq("user_id", str(current_user.id)).eq("order_id", order_id).single().execute()
        if not res.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        return res.data'''
        # UPDATED QUERY: Fetch nested products(product_name, image_url)
        res = supabase.table("orders").select("*, order_items(*, products(product_name,category, image_url))").eq("user_id", str(current_user.id)).eq("order_id", order_id).single().execute()
        if not res.data: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        
       
        return res.data
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

# --- NEW: PAYMENT VERIFICATION ENDPOINT ---


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
            .select("*, order_items(*, products(product_name,category, image_url))")
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

    # 3. Update DB
    try:
        update_data = {
            "payment_status": "Completed",
            "order_status": "Confirmed",
            "razorpay_payment_id": data.razorpay_payment_id
        }
        supabase.table("orders").update(update_data).eq("order_id", data.order_id).execute()
        
        return {"status": "success", "message": "Payment verified and order confirmed"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"DB update failed: {e}")
    


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
            .select("variant_id, product_id, color, size, stock_quantity")
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
            .select("variant_id, product_id, color, size, stock_quantity")
        )

        if product_id is not None:
            query = query.eq("product_id", product_id)

        result = (
            query
            .order("product_id")
            .order("color")
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
            .select("variant_id, product_id, color, size, stock_quantity")
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