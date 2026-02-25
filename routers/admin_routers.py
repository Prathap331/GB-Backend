from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import Header, HTTPException
import razorpay
from services import (
    send_order_email,
    supabase_admin,
    razorpay_client,
    get_current_user
)
from schemas.admin_schemas import (
    AdminCouponCreateRequest, BrandResponse, CategoryResponse,
    DeliveryPartner,
    PaymentVerificationRequest
)
from schemas.returns_schemas import (ReturnResponse, ReturnStatusEnum, ReturnUpdate )
from schemas.auth_schemas import UserResponse


router = APIRouter(tags=["Routers"])



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




@router.post("/admin/coupons")
async def create_coupon_admin(payload: AdminCouponCreateRequest):
    """Admin coupon creation flow:
    1️⃣ Resolve brand_id & brand_code (if brand-specific)
    2️⃣ Resolve partner_id & partner_code (if partner-specific)
    3️⃣ Generate coupon code (AUTO ONLY)
    4️⃣ Insert coupon
    5️⃣ Return coupon details"""

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
                supabase_admin
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
                supabase_admin
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
            supabase_admin
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



@router.post("/payment/verify")
async def verify_payment(
    data: PaymentVerificationRequest,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Verify a Razorpay payment signature.
    """

    # -------------------------------------------------
    # 1️⃣ Check if order exists
    # -------------------------------------------------
    try:
        order_res = (
            supabase_admin
            .table("orders")
            .select("*")
            .eq("order_id", data.order_id)
            .eq("user_id", str(current_user.id))
            .single()
            .execute()
        )

        if not order_res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )

        order = order_res.data

        if order["payment_status"] == "Completed":
            return {"status": "success", "message": "Payment already verified"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching order: {e}"
        )

    # -------------------------------------------------
    # 2️⃣ Verify Razorpay Signature
    # -------------------------------------------------
    try:
        params_dict = {
            "razorpay_order_id": data.razorpay_order_id,
            "razorpay_payment_id": data.razorpay_payment_id,
            "razorpay_signature": data.razorpay_signature,
        }

        razorpay_client.utility.verify_payment_signature(params_dict)

    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(
            status_code=400,
            detail="Payment verification failed: Invalid signature"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Verification error: {e}"
        )

    # -------------------------------------------------
    # 3️⃣ Update Order Status (Idempotent Safe)
    # -------------------------------------------------
    try:
        update_res = (
            supabase_admin
            .table("orders")
            .update({
                "payment_status": "Completed",
                "order_status": "Confirmed",
                "razorpay_payment_id": data.razorpay_payment_id,
            })
            .eq("order_id", data.order_id)
            .neq("payment_status", "Completed")
            .execute()
        )

        # Only if order was actually updated
        if update_res.data and len(update_res.data) > 0:
            updated_order = update_res.data[0]

            # -----------------------------------------
            # 3️⃣.1 Increment Coupon Usage
            # -----------------------------------------
            if updated_order.get("coupon_id"):
                coupon_res = (
                    supabase_admin
                    .table("coupons")
                    .select("coupon_id, used_count")
                    .eq("coupon_id", updated_order["coupon_id"])
                    .maybe_single()
                    .execute()
                )

                if coupon_res and coupon_res.data:
                    current_used = coupon_res.data.get("used_count", 0)

                    supabase_admin.table("coupons").update({
                        "used_count": current_used + 1
                    }).eq(
                        "coupon_id",
                        coupon_res.data["coupon_id"]
                    ).execute()

            # -----------------------------------------
            # 3️⃣.2 Fetch Order Items For Email
            # -----------------------------------------
            items_res = (
                supabase_admin
                .table("order_items")
                .select("quantity, price_per_unit, products(product_name)")
                .eq("order_id", data.order_id)
                .execute()
            )

            items_for_email = []

            for item in (items_res.data or []):
                items_for_email.append({
                    "product_name": item["products"]["product_name"],
                    "quantity": item["quantity"],
                    "price_per_unit": item["price_per_unit"],
                })

            # -----------------------------------------
            # 3️⃣.3 Send Confirmation Email
            # -----------------------------------------
            if current_user.email:
                background_tasks.add_task(
                    send_order_email,
                    current_user.email,
                    data.order_id,
                    updated_order["total_amount"],
                    items_for_email
                )

        return {
            "status": "success",
            "message": "Payment verified and order confirmed"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"DB update failed: {e}"
        )
    


# --- Delivery Partner Endpoints ---
@router.get("/delivery-partners", response_model=List[DeliveryPartner])
async def get_delivery_partners(current_user: UserResponse = Depends(get_current_user)):
    """ 
    Fetch all delivery partners. This is a public endpoint but we can keep it here for admin management of partners.
    """
    try:
        res = supabase_admin.table("delivery_partners").select("*").execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))




@router.get("/brands", response_model=List[BrandResponse])
def get_brands():
    """Fetch all brands"""
    res = (
        supabase_admin.table("brands").select("*").execute()
    )

    if not res.data:
        return []

    return res.data


@router.get("/categories", response_model=List[CategoryResponse])
def get_categories(segment: Optional[str] = Query(default=None)):
    """Fetch all categories, optionally filtered by segment - Men or Women"""
    try:
        query = supabase_admin.table("categories").select("*")

        if segment:
            query = query.eq("segment", segment)

        res = query.execute()

        return res.data or []

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch categories: {str(e)}")



@router.get("/coupons")
async def get_all_coupons():
    
    """
    Get all coupons for Admin view. This endpoint is separate from any customer-facing coupon endpoints, and returns all coupons regardless of active status or validity.
    """

    try:
        res = (
            supabase_admin
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



