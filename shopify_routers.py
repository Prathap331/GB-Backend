import os
import urllib.parse
import uuid
from fastapi import APIRouter, HTTPException, Request
import requests
from fastapi.responses import RedirectResponse
from services import supabase_admin
from utils import dump_shopify_debug, map_shopify_product, map_shopify_variant, upsert_product, upsert_variant

router = APIRouter(prefix="/shopify", tags=["Shopify"])

SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID")
SHOPIFY_REDIRECT_URL = os.getenv("SHOPIFY_REDIRECT_URL")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET")


@router.get("/install")
def shopify_install():
    state = str(uuid.uuid4())

    params = {
        "client_id": SHOPIFY_CLIENT_ID,
        "scope": "read_products",
        "redirect_uri": SHOPIFY_REDIRECT_URL,
        "state": state,
    }

    install_url = (
        "https://admin.shopify.com/oauth/authorize?"
        + urllib.parse.urlencode(params)
    )

    return {"install_url": install_url}

@router.get("/oauth/callback")
def shopify_oauth_callback(request: Request):
    code = request.query_params.get("code")
    shop = request.query_params.get("shop")

    if not code or not shop:
        raise HTTPException(status_code=400, detail="Missing code or shop")

    # 1. Exchange code for access token
    token_url = f"https://{shop}/admin/oauth/access_token"

    payload = {
        "client_id": SHOPIFY_CLIENT_ID,
        "client_secret": SHOPIFY_CLIENT_SECRET,
        "code": code,
    }

    res = requests.post(token_url, json=payload, timeout=10)

    if res.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to get access token")

    access_token = res.json().get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="No access token returned")

    # 2. Check if supplier already exists (SAFE WAY)
    existing = (
        supabase_admin.table("suppliers")
        .select("supplier_id")
        .eq("shop_domain", shop)
        .execute()
    )

    # 3A. Supplier NOT found → INSERT
    if not existing or not existing.data:
        supabase_admin.table("suppliers").insert({
            "shop_domain": shop,
            "shop_access_token": access_token,
            "integration_type": "shopify",
            "is_active": True
        }).execute()

        return RedirectResponse(
            url="https://qdio.in/shopify-connected",
            status_code=302
        )

    # 3B. Supplier already exists → UPDATE
    supplier_id = existing.data[0]["supplier_id"]

    supabase_admin.table("suppliers").update({
        "shop_access_token": access_token,
        "is_active": True
    }).eq("supplier_id", supplier_id).execute()

    return RedirectResponse(
        url="https://qdio.in/shopify-already-connected",
        status_code=302
    )



@router.post("/sync-products/{supplier_id}")
def sync_shopify_products(supplier_id: str):
    """
    Fetch products from a Shopify supplier and store in QDIO DB
    """

    # 1. Fetch supplier
    supplier_res = (
        supabase_admin.table("suppliers")
        .select("supplier_id, shop_domain, shop_access_token, integration_type")
        .eq("supplier_id", supplier_id)
        .single()
        .execute()
    )

    if not supplier_res.data:
        raise HTTPException(status_code=404, detail="Supplier not found")

    supplier = supplier_res.data

    if supplier["integration_type"] != "shopify":
        raise HTTPException(status_code=400, detail="Not a Shopify supplier")

    shop = supplier["shop_domain"]
    token = supplier["shop_access_token"]

    if not shop or not token:
        raise HTTPException(status_code=400, detail="Shopify credentials missing")

    # 2. Call Shopify Products API (VALID URL)
    url = f"https://{shop}/admin/api/2024-01/products.json"

    headers = {
        "X-Shopify-Access-Token": token
    }

    res = requests.get(url, headers=headers, timeout=15)

    if res.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch products from Shopify ({res.status_code})"
        )

    products = res.json().get("products", [])

    dump_shopify_debug(products, shop, token)


    
    # # 3. Map & store products
    # synced = 0

    # for p in products:
    #     # 1. Save base product
    #     product_res = upsert_product(
    #         map_shopify_product(p, supplier_id)
    #     )

    #     product_id = product_res.data[0]["product_id"]

    #     # 2. Save variants
    #     for v in p.get("variants", []):
    #         upsert_variant(
    #             map_shopify_variant(v, product_id)
    #         )
    #     synced += 1

    # return {
    #     "message": "Shopify products synced successfully",
    #     "count": synced
    # }

    return {
        "message": "Shopify products exported to CSV/JSON only. DB sync skipped.",
        "count": len(products)
    }