from fastapi import APIRouter, Depends, HTTPException
from fastapi import Header, HTTPException
from services import (
    supabase_admin,
    get_current_user
)
from schemas.partners_schemas import (
     PartnerActivateRequest, PartnerCreate, PartnerDashboardResponse, PartnerResponse
)
from schemas.auth_schemas import UserResponse

router = APIRouter(prefix="/partners", tags=["Partners"])


@router.post("/activate")
async def activate_partner(
    payload: PartnerActivateRequest,
    user: UserResponse = Depends(get_current_user)
):
    """
    Activate partner access for a user. This is a protected endpoint that requires the user to be authenticated. The user must provide a valid partner_id that matches an existing partner application. Once activated, the user's profile will be updated to reflect their partner status, allowing them access to partner-specific features and dashboards.
    """
    # 1️⃣ Validate partner_id
    partner_res = (
        supabase_admin
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
        supabase_admin
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
    supabase_admin.table("profiles").update({
        "is_partner": True,
        "partner_id": str(payload.partner_id)
    }).eq("id", str(user.id)).execute()

    return {
        "status": "success",
        "message": "Partner access activated"
    }


@router.post("/", response_model=PartnerResponse)
def submit_partner_application(payload: PartnerCreate):
    """
    Public endpoint for submitting a partner application."""
    try:
        res = supabase_admin.table("partners").insert(payload.model_dump()).execute()

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
@router.get("/", response_model=list[PartnerResponse])
def get_all_partner_applications():
    """
    Admin endpoint to fetch all partner applications. This can be used in the admin dashboard to review and manage partner applications."""
    res = supabase_admin.table("partners").select("*").order("created_at", desc=True).execute()
    return res.data


@router.get("/coupons")
async def get_partner_coupons(
    user: UserResponse = Depends(get_current_user)
):
    """
    Get all active coupons for the partner associated with the current user. This endpoint verifies the user's partner status and then retrieves all coupons linked to that partner."""
    # 1️⃣ Resolve partner
    partner_res = (
        supabase_admin.table("partners")
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
        supabase_admin.table("coupons")
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



@router.get("/dashboard", response_model=PartnerDashboardResponse)
async def get_partner_dashboard(
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get dashboard metrics for the partner associated with the current user. 
    This endpoint aggregates data across multiple tables to provide insights such as total sales, coupon performance, and associated brands. 
    It first verifies the user's partner status, then retrieves relevant coupons, orders, and products to calculate key metrics for the partner dashboard.
    """
    # =====================================================
    # 1️⃣ Verify partner from profiles (WORKING LOGIC)
    # =====================================================
    profile_res = (
        supabase_admin
        .table("profiles")
        .select("partner_id, is_partner")
        .eq("id", str(current_user.id))
        .maybe_single()
        .execute()
    )

    if not profile_res or not profile_res.data:
        raise HTTPException(404, "Profile not found")

    if not profile_res.data["is_partner"]:
        raise HTTPException(403, "Not a partner account")

    partner_id = profile_res.data["partner_id"]

    # =====================================================
    # 2️⃣ Partner basic info
    # =====================================================
    partner_res = (
        supabase_admin
        .table("partners")
        .select("full_name")
        .eq("partner_id", partner_id)
        .maybe_single()
        .execute()
    )

    partner_name = partner_res.data["full_name"] if partner_res.data else ""

    # =====================================================
    # 3️⃣ Partner coupons
    # =====================================================
    coupons_res = (
        supabase_admin
        .table("coupons")
        .select("""
            coupon_id,
            coupon_code,
            is_active,
            used_count,
            brand_id
        """)
        .eq("partner_id", partner_id)
        .execute()
    )

    coupons = coupons_res.data or []

    total_coupons = len(coupons)
    active_coupons = [c for c in coupons if c["is_active"]]
    active_coupon_codes = [c["coupon_code"] for c in active_coupons]
    total_coupon_usage = sum(c["used_count"] for c in coupons)

    coupon_ids = [c["coupon_id"] for c in coupons]

    # =====================================================
    # 4️⃣ Orders using partner coupons (🔥 FIXED PART)
    # =====================================================
    orders = []
    total_sale_value = 0.0

    if coupon_ids:
        orders_res = (
            supabase_admin
            .table("orders")
            .select("order_id, total_amount")
            .in_("coupon_id", coupon_ids)
            .eq("payment_status", "Completed")
            .execute()
        )

        orders = orders_res.data or []
        total_sale_value = round(
            sum(o["total_amount"] for o in orders),
            2
        )

    total_orders = len(orders)

    # =====================================================
    # 5️⃣ Products sold
    # =====================================================
    products_sold = 0
    if orders:
        order_ids = [o["order_id"] for o in orders]

        items_res = (
            supabase_admin
            .table("order_items")
            .select("quantity")
            .in_("order_id", order_ids)
            .execute()
        )

        products_sold = sum(i["quantity"] for i in (items_res.data or []))

    # =====================================================
    # 6️⃣ Partner brands
    # =====================================================
    brand_ids = {c["brand_id"] for c in coupons if c["brand_id"]}
    brand_names = []

    if brand_ids:
        brand_res = (
            supabase_admin
            .table("brands")
            .select("brand_name")
            .in_("brand_id", list(brand_ids))
            .execute()
        )

        brand_names = [b["brand_name"] for b in (brand_res.data or [])]

    # =====================================================
    # 7️⃣ Earnings (6% commission)
    # =====================================================
    total_earnings = round(total_sale_value * 0.06, 2)

    # =====================================================
    # 8️⃣ Response
    # =====================================================
    return {
        "partner_id": partner_id,
        "partner_name": partner_name,

        "total_sale_value": total_sale_value,

        "total_coupons": total_coupons,
        "active_coupons_count": len(active_coupons),
        "active_coupon_codes": active_coupon_codes,
        "total_coupon_usage": total_coupon_usage,

        "total_orders": total_orders,
        "products_sold": products_sold,

        "associated_brands": brand_names,
        "total_earnings": total_earnings,
    }
