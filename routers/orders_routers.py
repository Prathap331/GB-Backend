from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status, Response
from typing import List, Optional
from datetime import datetime, timedelta, timezone
import uuid
from fastapi import Header, HTTPException
from services import (
    get_user_supabase,
    send_order_email,
    supabase_admin,
    razorpay_client,
    RAZORPAY_KEY_ID,
    get_current_user
)
from schemas.auth_schemas import UserResponse
from schemas.orders_schemas import (
    Order, OrderCreate, OrderUpdate
)
from schemas.admin_schemas import (
    DeliveryStatusCreate, DeliveryStatusEnum
)

from utils import (
    generate_pdf_invoice,
    generate_unique_lucky_numbers
)


router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("/price-preview")
async def price_preview(order: OrderCreate):
    """
    Calculate the price breakdown for a potential order without actually creating it.
    """

    validated_items = []

    # ---------------------------------
    # 1️⃣ Validate items (SOURCE OF TRUTH)
    # ---------------------------------
    for item in order.items:
        variant = (
            supabase_admin.table("product_variants")
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
            supabase_admin.table("products")
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
            supabase_admin.table("coupons")
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

    shipping = 0.0 if final < 499 else 0.0
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
@router.post("/", response_model=Order)
async def create_order(
    order: OrderCreate,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Create a new order using variant_id (size-based).
    Validates stock from product_variants and stores variant_id in order_items.
    """

    # 1️⃣ Get user profile / address
    try:
        profile_res = (
            supabase_admin.table("profiles")
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
            supabase_admin.table("profiles").insert(profile).execute()

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
                supabase_admin.table("product_variants")
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
                supabase_admin.table("products")
                .select("product_id, product_name, brand_id, price, supplier_id, supplier_product_id, color")
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
                "product_name": p["product_name"],
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
            supabase_admin.table("coupons")
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

        order_res = supabase_admin.table("orders").insert(order_data).execute()
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

        supabase_admin.table("order_items").insert(items_payload).execute()

    except Exception as e:
        supabase_admin.table("orders").delete().eq("order_id", new_order_id).execute()
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

            supabase_admin.table("orders").update(
                {"razorpay_order_id": razorpay_order_id}
            ).eq("order_id", new_order_id).execute()

        except Exception as e:
            supabase_admin.table("orders").delete().eq("order_id", new_order_id).execute()
            raise HTTPException(500, f"Razorpay creation failed: {e}")



    #  DEDUCT STOCK PER VARIANT
    for item in validated_items:
        (
            supabase_admin
            .table("product_variants")
            .update({"stock_quantity": item["new_stock"]})
            .eq("variant_id", item["variant_id"])
            .execute()
        )

    # =====================================================
    # 9️⃣ COUPON USAGE (COD ONLY)
    # =====================================================
    if coupon_data and order.payment_method == "COD":
        supabase_admin.table("coupons").update({
            "used_count": coupon_data["used_count"] + 1
        }).eq("coupon_id", coupon_data["coupon_id"]).execute()

    # 10. RETURN FINAL ORDER
    order_res = (
        supabase_admin.table("orders")
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

    # Send email only for COD
    if order.payment_method == "COD" and current_user.email:
        background_tasks.add_task(
            send_order_email,
            current_user.email,
            new_order_id,
            grand_total,
            validated_items
        )

    return final_order



@router.get("/")
async def get_orders(
    partner_id: Optional[str] = Query(None, description="Filter orders by partner_id")
):
    """
    Get all orders.
    Optionally filter by partner_id (DD).
    """

    query = (
        supabase_admin
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



@router.get("/me", response_model=List[Order])
async def get_my_orders(current_user: UserResponse = Depends(get_current_user)):
    """
    Get all orders for the current user.
    """
    sb = get_user_supabase(current_user.token)
    try:
        orders_res = (
            sb  
            .table("orders")
            .select(
                "*, order_items(*, products(product_name,category,sub_category,images))"
            )
            .eq("user_id", str(current_user.id))
            .order("created_at", desc=True)
            .execute()
        )

        returns_res = (
            sb
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


@router.get("/me/{order_id}", response_model=Order)
async def get_my_single_order(
    order_id: int,
    current_user: UserResponse = Depends(get_current_user)):
    """
    Get a single order by ID for the current user, including return eligibility and status for each item.
    """
    try:
        sb = get_user_supabase(current_user.token)
        res = (
            sb
            .table("orders")
            .select(
                """
                *,
                order_items(
                    *,
                    products(product_name,category,sub_category,images)
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


@router.put("/{order_id}", response_model=Order)
async def update_order(
    order_id: int,
    order_update: OrderUpdate,
    current_user: UserResponse = Depends(get_current_user),):
    """
    Update opt_out_delivery.
    """
    try:
        # check order
        sb = get_user_supabase(current_user.token)
        existing_res = (
            sb
            .table("orders")
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
            sb.table("orders")
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
            sb.table("orders")
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




# --- UPDATED ENDPOINT: Download Invoice (With Payment Check) ---
@router.get("/{order_id}/invoice")
async def get_order_invoice(order_id: int, current_user: UserResponse = Depends(get_current_user)):
    """
    Generate and download a PDF invoice for a specific order.
    Only allows download if payment_status is 'Completed'.
    """
    try:
        # 1. Fetch Order details
        order_res = supabase_admin.table("orders").select("*, order_items(*, products(product_name, category))").eq("order_id", order_id).eq("user_id", str(current_user.id)).execute()
        
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
        user_res = supabase_admin.table("profiles").select("*").eq("id", str(current_user.id)).execute()
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



@router.post("/admin/{order_id}/delivery-status")
async def update_delivery_status(
    order_id: int,
    payload: DeliveryStatusCreate,
):
    
    """
    Admin endpoint to update delivery status of an order.
     - Logs every status update in delivery_status table.
        - If status is updated to 'Delivered', it also updates the delivery_date and return_valid_till in orders table.
        - This endpoint is intended to be used by the delivery partner or admin interface to keep track of delivery progress. 
    """
    # 1️⃣ Check order exists
    order_res = (
        supabase_admin
        .table("orders")
        .select("order_id, delivery_date")
        .eq("order_id", order_id)
        .single()
        .execute()
    )

    if not order_res.data:
        raise HTTPException(status_code=404, detail="Order not found")

    # 2️⃣ Insert into delivery_status log
    supabase_admin.table("delivery_status").insert({
        "order_id": order_id,
        "delivery_partner_id": payload.delivery_partner_id,
        "status": payload.status.value,   # IMPORTANT
        "remarks": payload.remarks
    }).execute()

    # 3️⃣ If Delivered → update orders table
    if payload.status == DeliveryStatusEnum.DELIVERED:
        if order_res.data["delivery_date"] is None:
            now = datetime.now(timezone.utc)
            supabase_admin.table("orders").update({
                "delivery_date": now.isoformat(),
                "return_valid_till": (now + timedelta(days=7)).isoformat()
            }).eq("order_id", order_id).execute()

    return {
        "message": "Delivery status updated successfully",
        "status": payload.status.value
    }

