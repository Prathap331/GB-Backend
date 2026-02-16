from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta, timezone
from fastapi import Header, HTTPException

from services import (
    get_user_supabase,
    get_current_user, 
    supabase_admin
)

from schemas.returns_schemas import (
    ReturnCreate, ReturnResponse, ReturnStatusEnum, ReturnUpdate
)
from schemas.auth_schemas import UserResponse


router = APIRouter(prefix="/returns", tags=["Returns"])

now = datetime.now(timezone.utc)
return_valid_till = now + timedelta(days=7)


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
    """
    Create a return request for a specific order item. 
    This endpoint validates the return request against the order details, including delivery status and return window. 
    It ensures that the requested variant is part of the order and prevents duplicate return requests for the same item. Upon successful validation, it creates a new return record in the database with the provided details and returns the status of the return request."""

    sb = get_user_supabase(current_user.token)
    try:
        # 1️⃣ Fetch order
        order_res = (
            sb.table("orders")
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
            sb.table("order_items")
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
            sb.table("returns")
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


        res = sb.table("returns").insert(insert_data).execute()

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
    """
    Get all return requests for a specific order. 
    This endpoint retrieves all return records associated with the given order ID and the currently authenticated user. 
    It ensures that users can only access their own return requests and provides details such as return status, product information, and timestamps for each return request."""
    
    sb = get_user_supabase(current_user.token)
    res = (
        sb
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



@router.patch("/{return_id}", response_model=ReturnResponse)
async def update_return_status(
    return_id: int,
    payload: ReturnUpdate
):
    """ Admin endpoint to update the status of a return request. This endpoint allows administrators to change the status of a return request (e.g., from "pending" to "approved" or "rejected"). It validates the provided return ID, updates the status in the database, and returns the updated return record with the new status and timestamps."""
    res = (
        supabase_admin
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
    """ 
    Admin endpoint to fetch all return requests, with optional filtering by status. 
    This endpoint retrieves all return records from the database and allows administrators to filter the results based on the return status (e.g., "pending", "approved", "rejected"). 
    It returns a list of return requests with their details, including timestamps converted to IST for easier readability."""
    query = supabase_admin.table("returns").select("*")

    if status:
        query = query.eq("status", status.value)

    res = query.order("initiated_at", desc=True).execute()

    # Convert to IST
    for r in res.data:
        r["initiated_at"] = to_ist(r["initiated_at"])
        r["updated_at"] = to_ist(r["updated_at"])

    return res.data



