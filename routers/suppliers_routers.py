from fastapi import APIRouter, HTTPException
from typing import List
from fastapi import Header, HTTPException
from services import (
    SYNC_SECRET,
    fetch_supplier_products,
    supabase_admin
)
from schemas.suppliers_schemas import Supplier

from utils import (
    map_supplier_product,
    upsert_product,
)



router = APIRouter(tags=["Suppliers"])



@router.post("/sync/supplier/{supplier_id}")
async def sync_supplier_products(
    supplier_id: str,
    x_sync_secret: str = Header(None)
):
    """
    Sync products for a specific supplier.
    This endpoint allows authorized clients to sync supplier products with the QDIO database.
    It requires a valid sync secret in the request headers for security purposes.
    """

    if x_sync_secret != SYNC_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    supplier_products = fetch_supplier_products()

    synced = 0
    for p in supplier_products:
        mapped = map_supplier_product(p, supplier_id)
        upsert_product(mapped)
        synced += 1

    return {"status": "ok", "synced": synced}





@router.get("/suppliers", response_model=List[Supplier])
async def get_suppliers():
    """
    Fetch all suppliers from the database. 
    This endpoint retrieves a list of all suppliers registered in the system, including their details such as supplier ID, name, shop domain, and integration type.
    """
    try:
        res = supabase_admin.table("suppliers").select("*").execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
