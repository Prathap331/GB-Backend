from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List
from datetime import datetime
from fastapi import Header, HTTPException
import json

from services import (
    supabase_admin,
    get_current_user
)
from schemas.product_schemas import (
    Product, ProductUpdate
)
from schemas.auth_schemas import UserResponse


router = APIRouter(prefix="/products", tags=["Products"])



# --- Product Endpoints ---

@router.get("/", response_model=List[Product])
async def get_products():
    try:
        res = supabase_admin.table("products").select("*").order("created_at", desc=True).execute()
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


@router.get("/{product_id}", response_model=Product)
async def get_product(product_id: int):
    try:
        res = supabase_admin.table("products").select("*").eq("product_id", product_id).single().execute()
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


@router.get("/base/{base_product_id}", response_model=List[Product])
async def get_products_by_base_id(base_product_id: int):
    try:
        res = (
            supabase_admin.table("products")
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
@router.put("/{product_id}", response_model=Product)
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
        res = supabase_admin.table("products").update(update_data).eq("product_id", product_id).execute()
        if not res.data or len(res.data) == 0:
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found or update failed")
        return res.data[0]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))



@router.get("/{product_id}/variants")
def get_product_variants(product_id: int):

    try:
        result = (
            supabase_admin
            .table("product_variants")
            .select("variant_id, product_id, size, stock_quantity,mrp,price")
            .eq("product_id", product_id)
            .execute()
        )

        # result.data will always exist — may just be []
        return result.data

    except Exception as e:
        raise HTTPException(500, f"Failed to fetch variants: {e}")



#  to fetch one specific size+color
@router.get("/variants/{variant_id}")
def get_variant(variant_id: int):

    try:
        result = (
            supabase_admin
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

